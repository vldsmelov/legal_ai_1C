from typing import List, Tuple, Dict, Any
from .types import SectionScore, FocusItem
from .config import settings

SECTION_DEFS = [
    {"key": "parties", "title": "Идентификация сторон, полномочия, реквизиты", "weight": 8},
    {"key": "scope", "title": "Предмет/результат, измеримость (SOW/ТЗ)", "weight": 10},
    {"key": "timeline_acceptance", "title": "Сроки, поставка/оказание, приемка, milestones", "weight": 8},
    {"key": "payment", "title": "Цена, налоги, порядок платежей, удержания", "weight": 10},
    {"key": "liability", "title": "Ответственность, неустойки/штрафы, лимиты (cap)", "weight": 10},
    {"key": "reps_warranties", "title": "Гарантии и заверения сторон", "weight": 6},
    {"key": "ip", "title": "IP/права на результаты, лицензии, отчуждение", "weight": 8},
    {"key": "confidentiality", "title": "Конфиденциальность/коммерческая тайна", "weight": 6},
    {"key": "personal_data", "title": "Персональные данные/данные (GDPR/152-ФЗ и пр.)", "weight": 8},
    {"key": "force_majeure", "title": "Форс-мажор", "weight": 4},
    {"key": "change_termination", "title": "Изменение/расторжение, односторонний отказ", "weight": 6},
    {"key": "law_venue", "title": "Применимое право и подсудность/арбитраж", "weight": 6},
    {"key": "conflicts_priority", "title": "Конфликты/приоритет документов, приложения", "weight": 5},
    {"key": "signatures_form", "title": "Подписи, форма сделки, экземпляры/ЭП", "weight": 5},
]
SECTION_INDEX = {s["key"]: s for s in SECTION_DEFS}

WHY_MAP = {
    "scope": "Неясный предмет лишает договор исполнимости и мешает приемке.",
    "payment": "Неопределённая цена/сроки оплаты создают риски споров и кассовых разрывов.",
    "liability": "Отсутствие лимита ответственности ведёт к непропорциональным рискам.",
    "ip": "Без явной передачи/лицензии права на результаты могут остаться у исполнителя.",
    "timeline_acceptance": "Нет процедуры приемки — спорно, когда обязательства исполнены.",
    "personal_data": "Нарушения по ПДн чреваты штрафами и запретом обработки.",
    "law_venue": "Без права и подсудности сложнее защищать интересы и исполнять решения.",
    "confidentiality": "Без NDA утечка сведений не контролируется.",
    "parties": "Ошибки в реквизитах/полномочиях делают договор оспоримым.",
    "change_termination": "Односторонние изменения без триггеров — дисбаланс и риски.",
    "conflicts_priority": "Конфликт документов рушит логику договора.",
    "signatures_form": "Ошибки в форме/подписи ведут к недействительности.",
    "reps_warranties": "Без заверений растут риски недостоверных сведений.",
    "force_majeure": "Нечёткий форс-мажор — злоупотребления и неопределённость.",
}
SUGGEST_MAP = {
    "scope": "Прописать измеримый результат/ТЗ и критерии приемки.",
    "payment": "Зафиксировать цену/сроки оплаты, аванс/удержания, налоги.",
    "liability": "Установить cap ответственности и исключения.",
    "ip": "Определить передачу/лицензию прав: объём, территория, срок.",
    "timeline_acceptance": "Ввести форму акта, сроки и последствия просрочки.",
    "personal_data": "Добавить DPA/152-ФЗ: роли, цели, трансграничку, меры.",
    "law_venue": "Указать право РФ и подсудность/арбитраж.",
    "confidentiality": "Задать режим тайны, срок, исключения и ответственность.",
    "parties": "Проверить ОГРН/ИНН, полномочия, доверенности/ЭП.",
    "change_termination": "Определить основания и уведомления.",
    "conflicts_priority": "Добавить правило приоритета и реестр приложений.",
    "signatures_form": "Указать форму (бумага/ЭП), экз., порядок обмена.",
    "reps_warranties": "Заверения об отсутствии прав третьих лиц.",
    "force_majeure": "Согласовать перечень событий и порядок уведомления.",
}

def sections_lines() -> str:
    return "\n".join([f'- "{s["key"]}" — {s["title"]}' for s in SECTION_DEFS])

def compute_total_and_color(section_scores: List[SectionScore]) -> Tuple[int, str, List[Dict[str, Any]]]:
    items, total = [], 0.0
    for s in section_scores:
        meta = SECTION_INDEX.get(s.key)
        if not meta:
            continue
        weight = meta["weight"]
        weighted = (max(0, min(5, s.raw)) / 5.0) * weight
        total += weighted
        items.append({
            "key": s.key, "title": meta["title"], "weight": weight,
            "raw": s.raw, "score": round(weighted, 2), "of": weight,
            "comment": s.comment or ""
        })
    score_total = int(round(total))
    if score_total >= settings.SCORE_GREEN:
        color = "green"
    elif score_total >= settings.SCORE_YELLOW:
        color = "yellow"
    else:
        color = "red"
    return score_total, color, items

def build_focus(section_table: List[Dict[str, Any]], issues: List[Dict[str, Any]]) -> Tuple[str, List[FocusItem]]:
    sorted_sections = sorted(section_table, key=lambda x: (x["raw"], -x["weight"]))
    top: List[FocusItem] = []
    for row in sorted_sections[:3]:
        key = row["key"]
        why = WHY_MAP.get(key, "Низкая оценка раздела может привести к юридическим рискам.")
        sugg = next((it.get("suggestion") for it in issues if it.get("section") == key and it.get("suggestion")), None)
        top.append(FocusItem(
            key=key, title=row["title"], raw=row["raw"], score=row["score"],
            why=why, suggestion=sugg or SUGGEST_MAP.get(key)
        ))
    if not top:
        return "Серьёзных проблем не выявлено.", []
    focus_summary = "Обратить внимание: " + "; ".join([f"{t.title.lower()} — {t.why}" for t in top]) + "."
    return focus_summary, top
