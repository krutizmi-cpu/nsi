from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from config import DATA_DIR, NAME_MAX_LEN, TNVED_VAT_CONFIG_PATH, TNVED_VAT_LOOKUP_URL
from db_session import SessionLocal, init_db
from integrations.onec_client import get_default_onec_client
from models import BulkUploadTask, DuplicateCandidate, NsiGroup, NsiItem, OnecCatalogEntry
from services.barcode_flow import resolve_barcode
from services.bulk_upload import (
    get_bulk_upload_stats,
    process_all_pending_tasks,
    upload_excel_batch,
)
from services.dimensions_service import volume_m3_from_mm
from services.duplicates import find_similar_items, record_duplicate_candidates
from services.groups_onec import ensure_group_from_onec_path
from services.nomenclature import suggest_next_article, validate_article, validate_name
from services.onec_excel import import_onec_catalog_from_bytes, suggest_catalog_matches
from services.stats_dimensions import suggest_peer_medians
from services.supplier_fetch import fetch_dimensions_from_supplier_url
from services.supplier_parsers.registry import reload_supplier_site_config, resolve_parser_id_for_url
from services.tnved_vat import describe_tnved_hint, normalize_tnved, reload_tnved_vat_rules, suggest_vat_percent_by_tnved
from services.units import LengthUnit, WeightUnit, normalize_dimensions_mm, normalize_weight_kg


def _bootstrap() -> None:
    init_db()
    with SessionLocal() as session:
        if session.execute(select(NsiGroup.id).limit(1)).scalar_one_or_none() is None:
            session.add(NsiGroup(name="Без группы", parent_id=None))
            session.commit()


st.set_page_config(page_title="НСИ", page_icon="📋", layout="wide")
st.title("НСИ — номенклатура")

if "_nsi_flash" in st.session_state:
    st.success(st.session_state.pop("_nsi_flash"))

_bootstrap()

tab_catalog, tab_new, tab_excel, tab_bulk = st.tabs(["Каталог", "Новая позиция", "Справочник 1С (Excel)", "Массовая загрузка"])

with tab_catalog:
    with SessionLocal() as session:
        rows = session.execute(
            select(
                NsiItem.id,
                NsiItem.article,
                NsiItem.name,
                NsiItem.group_id,
                NsiItem.barcode,
                NsiItem.barcode_status,
                NsiItem.tnved_code,
                NsiItem.vat_rate_percent,
                NsiItem.length_mm,
                NsiItem.width_mm,
                NsiItem.height_mm,
                NsiItem.weight_kg,
                NsiItem.volume_m3,
                NsiItem.dimensions_source,
                NsiItem.supplier_parser_id,
            ).order_by(NsiItem.id.desc())
        ).all()
    if rows:
        st.dataframe(
            pd.DataFrame(
                rows,
                columns=[
                    "id",
                    "article",
                    "name",
                    "group_id",
                    "barcode",
                    "barcode_status",
                    "tnved_code",
                    "vat_%",
                    "L_mm",
                    "W_mm",
                    "H_mm",
                    "kg",
                    "m³",
                    "dim_src",
                    "parser",
                ],
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Позиций пока нет — добавьте на вкладке «Новая позиция».")

    with st.expander("Кандидаты на дубли (последние записи)"):
        with SessionLocal() as session:
            dups = session.execute(
                select(
                    DuplicateCandidate.item_id_1,
                    DuplicateCandidate.item_id_2,
                    DuplicateCandidate.similarity_score,
                ).order_by(DuplicateCandidate.id.desc()).limit(50)
            ).all()
        if dups:
            st.dataframe(pd.DataFrame(dups, columns=["id_1", "id_2", "score"]), hide_index=True)
        else:
            st.caption("Пока нет записей о похожих наименованиях.")

with tab_excel:
    st.markdown("Загрузите **полную** или частичную выгрузку номенклатуры из 1С в **Excel** (`.xlsx`). Колонки распознаются по заголовкам — см. `services/onec_excel.py`.")
    f = st.file_uploader("Файл Excel", type=["xlsx", "xls"])
    replace_all = st.checkbox("Очистить старый справочник перед загрузкой", value=False)
    if f is not None and st.button("Импортировать в справочник", type="primary"):
        data = f.read()
        with SessionLocal() as session:
            n, err = import_onec_catalog_from_bytes(session, data, replace_all=replace_all)
            if err:
                st.error(err)
            else:
                session.commit()
                st.session_state["_nsi_flash"] = f"Импортировано строк: {n}"
                st.rerun()
    with SessionLocal() as session:
        cnt = session.execute(select(func.count()).select_from(OnecCatalogEntry)).scalar_one()
    st.caption(f"Строк в справочнике 1С: **{cnt}**")

with tab_bulk:
    st.markdown("### Массовая загрузка новых позиций из Excel")
    st.info(
        "Загрузите Excel-файл с колонками:\n\n"
        "- **supplier_article** (артикул поставщика) — обязательно\n"
        "- **name** (наименование) — обязательно\n"
        "- **supplier_name** (наименование поставщика) — обязательно\n"
        "- **supplier_url** (ссылка на сайт поставщика) — обязательно\n"
        "- **barcode** (штрихкод) — необязательно\n"
        "- **length_mm, width_mm, height_mm, weight_kg** — необязательно\n\n"
        "Система автоматически:\n"
        "1. Спарсит данные с сайтов поставщиков (габариты, вес, ТН ВЭД)\n"
        "2. Определит категорию по базе\n"
        "3. Создаст позиции в НСИ"
    )
    
    bulk_file = st.file_uploader("Файл Excel для массовой загрузки", type=["xlsx", "xls"], key="bulk_upload_file")
    supplier_name_override = st.text_input(
        "Наименование поставщика (переопределение)",
        help="Если указано, будет использовано для всех строк вместо значения из файла",
        key="bulk_supplier_name"
    )
    
    if bulk_file is not None and st.button("Загрузить и создать задачи", type="primary"):
        file_bytes = bulk_file.read()
        with SessionLocal() as session:
            count, error = upload_excel_batch(session, file_bytes, supplier_name_override or None)
            if error:
                st.error(error)
            else:
                session.commit()
                st.session_state["_nsi_flash"] = f"Создано задач на обработку: {count}"
                st.success(f"✅ Создано задач: {count}")
                st.rerun()
    
    # Отображение статуса задач
    with SessionLocal() as session:
        stats = get_bulk_upload_stats(session)
        
    if stats["total"] > 0:
        st.subheader("Статистика задач")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("В ожидании", stats["pending"])
        with col2:
            st.metric("В обработке", stats["processing"])
        with col3:
            st.metric("Успешно", stats["completed"])
        with col4:
            st.metric("С ошибками", stats["failed"])
        
        if st.button("Обработать все ожидающие задачи"):
            with SessionLocal() as session:
                success, total = process_all_pending_tasks(session)
                st.session_state["_nsi_flash"] = f"Обработано: {success}/{total}"
                st.rerun()
        
        # Таблица последних задач
        st.subheader("Последние задачи")
        with SessionLocal() as session:
            recent_tasks = session.execute(
                select(BulkUploadTask).order_by(BulkUploadTask.created_at.desc()).limit(50)
            ).scalars().all()
        
        if recent_tasks:
            task_data = []
            for t in recent_tasks:
                task_data.append({
                    "ID": t.id,
                    "Артикул": t.supplier_article,
                    "Поставщик": t.supplier_name,
                    "URL": t.supplier_url[:50] + "..." if len(t.supplier_url) > 50 else t.supplier_url,
                    "Статус": t.status,
                    "Группа": t.suggested_group_name or "-",
                    "Ошибка": t.error_message[:50] if t.error_message else "-",
                    "Создано": t.created_at.strftime("%Y-%m-%d %H:%M"),
                })
            st.dataframe(pd.DataFrame(task_data), use_container_width=True, hide_index=True)
    else:
        st.caption("Задач на массовую загрузку пока нет.")

with tab_new:
    with SessionLocal() as session:
        groups = session.execute(select(NsiGroup.id, NsiGroup.name).order_by(NsiGroup.name)).all()
        articles = [r[0] for r in session.execute(select(NsiItem.article)).all()]
    group_options = {name: gid for gid, name in groups}
    group_names = list(group_options.keys())
    suggested = suggest_next_article(articles)

    col_a, col_b = st.columns([2, 1])
    with col_a:
        article = st.text_input("Артикул", placeholder=f"например {suggested}", key="nsi_article")
    with col_b:
        st.write("")
        st.write("")
        if st.button("Подставить следующий ТСР"):
            st.session_state["nsi_article"] = suggested
            st.rerun()

    av = validate_article(article)
    if not av.ok:
        st.warning(av.message)
        if av.suggested_article:
            st.caption(f"Пример: `{av.suggested_article}` (нажмите «Подставить следующий ТСР» для очередного номера)")

    name = st.text_area(
        f"Наименование (макс. {NAME_MAX_LEN} символов)",
        max_chars=NAME_MAX_LEN,
        height=100,
        key="nsi_name",
    )
    used = len(name or "")
    st.caption(f"Символов: {used} / {NAME_MAX_LEN}")
    nv_ok, nv_msg = validate_name(name or "")
    if not nv_ok:
        st.error(nv_msg)

    with SessionLocal() as session:
        matches = suggest_catalog_matches(session, name or "", limit=8)
    if matches and (name or "").strip():
        opts = [f"{row.code_1c or '—'} | {row.name[:60]}… ({score:.0%})" for row, score in matches]
        pick = st.selectbox("Подсказка из справочника 1С (по похожести наименования)", ["— не применять —"] + opts)
        if pick != "— не применять —" and st.button("Применить ТН ВЭД, НДС и группу из выбранной строки"):
            idx = opts.index(pick)
            row, _score = matches[idx]
            st.session_state["nsi_tnved"] = row.tnved_code or ""
            st.session_state["nsi_group_path_note"] = row.group_path or ""
            vr = row.vat_rate_percent
            if vr is not None:
                v = float(vr)
                if v in (0.0, 10.0, 20.0):
                    st.session_state["nsi_vat_pick"] = str(int(v)) if v == float(int(v)) else str(v)
                else:
                    st.session_state["nsi_vat_pick"] = ""
            else:
                st.session_state["nsi_vat_pick"] = ""
            with SessionLocal() as session:
                gid = ensure_group_from_onec_path(session, row.group_path)
                gname = None
                if gid is not None:
                    gr = session.get(NsiGroup, gid)
                    gname = gr.name if gr else None
                session.commit()
            if gname:
                st.session_state["nsi_group_name"] = gname
            st.rerun()

    default_group = st.session_state.get("nsi_group_name")
    idx_default = group_names.index(default_group) if default_group in group_names else 0
    group_name = st.selectbox("Группа (НСИ)", group_names, index=idx_default) if group_names else None
    group_id = group_options.get(group_name) if group_name else None
    if st.session_state.get("nsi_group_path_note"):
        st.caption(f"Путь из 1С: {st.session_state.get('nsi_group_path_note')}")

    tnved = st.text_input("ТН ВЭД", key="nsi_tnved")
    if tnved:
        st.caption(describe_tnved_hint(tnved))
    vat_labels = ["", "0", "10", "20"]
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        vat_pick = st.selectbox("Ставка НДС, %", vat_labels, key="nsi_vat_pick")
    with col_v2:
        if st.button("Подставить НДС по эвристике ТН ВЭД"):
            guess = suggest_vat_percent_by_tnved(tnved)
            if guess is not None:
                g = int(guess) if guess == float(int(guess)) else guess
                st.session_state["nsi_vat_pick"] = str(g)
                st.rerun()
            else:
                st.warning("Не удалось предложить ставку по коду — задайте вручную.")
    vat_manual = float(vat_pick) if vat_pick else None

    marking = st.selectbox(
        "Маркировка",
        ["", "не требуется", "Честный ЗНАК — одежда", "Честный ЗНАК — обувь", "другое"],
    )
    supplier_article = st.text_input("Артикул поставщика (для поиска штрихкода)", key="nsi_sup_art")
    barcode_manual = st.text_input("Штрихкод (вручную, если уже известен)", key="nsi_bc")

    bc_res = resolve_barcode(supplier_barcode=supplier_article, manual_barcode=barcode_manual)
    st.caption(f"Штрихкод: {bc_res.note} → статус `{bc_res.status}`")

    supplier_url = st.text_input(
        "URL карточки товара на сайте поставщика",
        key="nsi_supplier_url",
        help="Домен определяет парсер: список в `data/supplier_sites.json`, модули в `services/supplier_parsers/sites/`.",
    )
    if supplier_url.strip():
        pid = resolve_parser_id_for_url(supplier_url.strip())
        st.caption(f"Будет использован парсер **`{pid}`** (РФ/международные сайты — по URL).")
    if supplier_url.strip() and st.button("Загрузить с сайта (габариты / вес / при наличии ТН ВЭД)"):
        try:
            g = fetch_dimensions_from_supplier_url(supplier_url.strip())
            st.session_state["nsi_lmm"] = float(g.length_mm or 0.0)
            st.session_state["nsi_wmm"] = float(g.width_mm or 0.0)
            st.session_state["nsi_hmm"] = float(g.height_mm or 0.0)
            st.session_state["nsi_wkg"] = float(g.weight_kg or 0.0)
            st.session_state["nsi_dim_note"] = f"[парсер: {g.parser_id}] {g.raw_note}"
            st.session_state["nsi_dim_src"] = "supplier_site"
            st.session_state["nsi_last_parser"] = g.parser_id
            if g.tnved_code:
                st.session_state["nsi_tnved"] = g.tnved_code
                st.session_state["nsi_dim_note"] += f" Подставлен ТН ВЭД с сайта: {g.tnved_code} (проверьте)."
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"Не удалось загрузить: {e}")

    if st.session_state.get("nsi_dim_note"):
        st.info(st.session_state.get("nsi_dim_note"))

    st.subheader("Габариты и вес (канон: мм и кг)")
    c1, c2, c3 = st.columns(3)
    with c1:
        len_mm = st.number_input("Длина, мм", min_value=0.0, value=0.0, step=1.0, key="nsi_lmm")
    with c2:
        wid_mm = st.number_input("Ширина, мм", min_value=0.0, value=0.0, step=1.0, key="nsi_wmm")
    with c3:
        hei_mm = st.number_input("Высота, мм", min_value=0.0, value=0.0, step=1.0, key="nsi_hmm")
    w_kg = st.number_input("Вес, кг", min_value=0.0, value=0.0, step=0.001, format="%.3f", key="nsi_wkg")

    with st.expander("Ввод в других единицах (пересчёт в мм / кг)"):
        u_len = st.selectbox("Единица габаритов", ["mm", "cm", "m", "inch"], index=0)
        r1, r2, r3 = st.columns(3)
        with r1:
            lv = st.number_input("Длина", value=0.0, step=0.01)
        with r2:
            wv = st.number_input("Ширина", value=0.0, step=0.01)
        with r3:
            hv = st.number_input("Высота", value=0.0, step=0.01)
        u_w = st.selectbox("Единица веса", ["kg", "g", "lb"])
        wv_al = st.number_input("Вес", value=0.0, step=0.01)
        if st.button("Применить пересчёт"):
            lu = LengthUnit.MM if u_len == "mm" else LengthUnit.CM if u_len == "cm" else LengthUnit.M if u_len == "m" else LengthUnit.INCH
            l2, w2, h2 = normalize_dimensions_mm(lv, wv, hv, unit=lu)
            st.session_state["nsi_lmm"] = float(l2 or 0.0)
            st.session_state["nsi_wmm"] = float(w2 or 0.0)
            st.session_state["nsi_hmm"] = float(h2 or 0.0)
            wu = WeightUnit.KG if u_w == "kg" else WeightUnit.G if u_w == "g" else WeightUnit.LB
            st.session_state["nsi_wkg"] = float(normalize_weight_kg(wv_al, unit=wu) or 0.0)
            st.session_state["nsi_dim_src"] = "manual"
            st.rerun()

    if group_id and st.button("Подставить медиану габаритов по группе (≥3 позиций с заполненными полями)"):
        with SessionLocal() as session:
            ml, mw, mh, mk, _mv = suggest_peer_medians(session, group_id=group_id, exclude_item_id=None)
        if ml is not None:
            st.session_state["nsi_lmm"] = float(ml)
            st.session_state["nsi_wmm"] = float(mw or 0.0)
            st.session_state["nsi_hmm"] = float(mh or 0.0)
            if mk is not None:
                st.session_state["nsi_wkg"] = float(mk)
            st.session_state["nsi_dim_note"] = "Подставлена медиана по группе (статистика)."
            st.session_state["nsi_dim_src"] = "peer_median"
            st.rerun()
        else:
            st.warning("Недостаточно данных в группе для медианы.")

    l_fin = float(len_mm)
    w_fin = float(wid_mm)
    h_fin = float(hei_mm)
    vol = volume_m3_from_mm(
        l_fin if l_fin > 0 else None,
        w_fin if w_fin > 0 else None,
        h_fin if h_fin > 0 else None,
    )
    st.caption(f"Объём (расчёт): **{vol:.6f} м³**" if vol is not None else "Объём: укажите все три габарита > 0")

    dim_src = st.session_state.get("nsi_dim_src") or "manual"

    if st.button("Сохранить", type="primary"):
        if not av.ok or not nv_ok:
            st.error("Исправьте ошибки валидации.")
        else:
            with SessionLocal() as session:
                dup_check = find_similar_items(session, name or "", exclude_id=None)
                if dup_check:
                    names = ", ".join(f"{x.article} ({score:.0%})" for x, score in dup_check[:5])
                    st.warning(f"Похожие наименования уже есть: {names}. Сохраняем, запись попадёт в кандидаты дублей.")

                l_mm = l_fin if l_fin > 0 else None
                w_mm = w_fin if w_fin > 0 else None
                h_mm = h_fin if h_fin > 0 else None
                w_k = w_kg if w_kg and w_kg > 0 else None
                vol_c = volume_m3_from_mm(l_mm, w_mm, h_mm)

                item = NsiItem(
                    article=article.strip(),
                    name=(name or "").strip()[:NAME_MAX_LEN],
                    group_id=group_id,
                    tnved_code=normalize_tnved(tnved) or None,
                    vat_rate_percent=float(vat_manual) if vat_manual is not None else None,
                    marking_type=marking or None,
                    supplier_article=supplier_article.strip() or None,
                    barcode=bc_res.barcode,
                    barcode_status=bc_res.status,
                    length_mm=l_mm,
                    width_mm=w_mm,
                    height_mm=h_mm,
                    weight_kg=w_k,
                    volume_m3=vol_c,
                    dimensions_source=dim_src,
                    supplier_page_url=supplier_url.strip() or None,
                    supplier_parser_id=st.session_state.get("nsi_last_parser") if dim_src == "supplier_site" else None,
                    source="streamlit",
                )
                session.add(item)
                session.flush()

                similar = find_similar_items(session, item.name, exclude_id=item.id)
                record_duplicate_candidates(session, item, similar)
                session.commit()
                st.session_state["_nsi_flash"] = f"Сохранено: id={item.id}, артикул={item.article}"
                st.rerun()

with st.sidebar:
    st.subheader("РФ: ТН ВЭД и НДС")
    st.caption(f"Файл правил: `{TNVED_VAT_CONFIG_PATH.name}`")
    if TNVED_VAT_LOOKUP_URL:
        st.caption("Внешний URL подсказки НДС включён (`NSI_TNVED_VAT_LOOKUP_URL`).")
    else:
        st.caption("Внешний URL не задан — только JSON и эвристика.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Обновить правила НДС"):
            reload_tnved_vat_rules()
            st.success("Кэш ТН ВЭД/НДС сброшен.")
    with c2:
        if st.button("Обновить парсеры"):
            reload_supplier_site_config()
            st.success("Кэш `supplier_sites.json` сброшен.")
    st.markdown(f"Каталог данных: `{DATA_DIR}`")

    st.subheader("Интеграция 1С (заглушка)")
    client = get_default_onec_client()
    if st.button("Проверить LocalOneCClient.fetch"):
        with SessionLocal() as s:
            rows = client.fetch_nomenclature(s, since=None)
        st.write(f"Записей в каталоге: {len(rows)}")
