from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib import parse, request

try:
    import holidays
except ImportError:
    holidays = None

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# --- [설정] ---
BASE_URL = "https://xdungeon.net/layout/res/home.php"
ZIZUM_ID = 9
THEME_KEYWORD = "향"
THEME_INDEX = int(os.environ.get("DUNGEON_THEME_INDEX", "2"))  # 1-based
WAIT_SECONDS = 12
OPEN_HOUR_KST = 22

WEEKDAY_ONLY = "20:30"
HOLIDAY_START = "11:30"
HOLIDAY_END = "20:30"
KOR_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

BLOCKED_KEYWORDS = [
    "예약불가",
    "불가",
    "마감",
    "예약완료",
    "종료",
    "대기",
    "closed",
    "sold out",
    "soldout",
    "full",
]
AVAILABLE_KEYWORDS = ["예약가능", "가능", "예약", "open", "available", "신청"]

TELEGRAM_TOKEN = os.environ.get("MY_ALARM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("MY_CHAT_ID")
DEBUG = os.environ.get("DEBUG_SLOT", "0") == "1"


def get_kst_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def get_open_dates(now_kst: datetime) -> list[date]:
    total_days = 8 if now_kst.hour >= OPEN_HOUR_KST else 7
    return [(now_kst.date() + timedelta(days=offset)) for offset in range(total_days)]


def build_holiday_set(open_dates: list[date]) -> set[date]:
    if holidays is None:
        raise RuntimeError("공휴일 판별을 위해 holidays 패키지가 필요합니다. 설치: pip install holidays")
    years = sorted({d.year for d in open_dates})
    kr_holidays = holidays.country_holidays("KR", years=years)
    return set(kr_holidays.keys())


def build_url(target_date: str) -> str:
    params = {
        "go": "rev.main",
        "s_zizum": str(ZIZUM_ID),
        "rev_days": target_date,
    }
    return f"{BASE_URL}?{parse.urlencode(params)}"


def to_minutes(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm)


def is_in_allowed_time_range(slot_time: str, is_holiday: bool) -> bool:
    value = to_minutes(slot_time)
    if is_holiday:
        return to_minutes(HOLIDAY_START) <= value <= to_minutes(HOLIDAY_END)
    return value == to_minutes(WEEKDAY_ONLY)


def extract_time(text: str) -> str | None:
    for pattern in [
        r"\b([01]?\d|2[0-3]):([0-5]\d)\b",
        r"\b([01]?\d|2[0-3])\s*시\s*([0-5]?\d)\s*분?\b",
        r"\b([01]?\d|2[0-3])\s*시\b",
        r"\b([01]\d|2[0-3])([0-5]\d)\b",
    ]:
        m = re.search(pattern, text)
        if not m:
            continue
        if pattern.endswith("시\\b"):
            return f"{int(m.group(1)):02d}:00"
        if len(m.groups()) == 2:
            return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    return None


def extract_times(text: str) -> list[str]:
    matches = re.findall(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    result = []
    seen = set()
    for hh, mm in matches:
        value = f"{int(hh):02d}:{mm}"
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def has_blocked_signal(text: str, classes: str, disabled_attr: str | None, aria_disabled: str) -> bool:
    if disabled_attr is not None or aria_disabled == "true":
        return True

    lowered = text.lower()
    lowered_classes = classes.lower()
    if any(token in lowered_classes for token in ["disabled", "close", "sold", "full", "finish"]):
        return True
    return any(token in lowered for token in BLOCKED_KEYWORDS)


def has_available_hint(text: str, classes: str) -> bool:
    lowered = text.lower()
    if any(token in lowered for token in AVAILABLE_KEYWORDS):
        return True
    lowered_classes = classes.lower()
    return any(token in lowered_classes for token in ["btn", "time", "reserve", "slot"])


def _has_time_pattern(text: str) -> bool:
    return re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text) is not None


def _pick_theme_containers(driver: webdriver.Chrome) -> list[Any]:
    # 핵심: thm_box(전체 묶음) 제외, 개별 테마 박스(.box)만 대상으로 한다.
    boxes = []
    for selector in [".thm_box > .box", ".thm_box .box", ".box"]:
        boxes.extend(driver.find_elements(By.CSS_SELECTOR, selector))

    # 중복 제거
    uniq: list[Any] = []
    seen = set()
    for box in boxes:
        key = box.id
        if key in seen:
            continue
        seen.add(key)
        uniq.append(box)

    # 1) 향 키워드 박스 우선
    keyword_hits = []
    for elem in uniq:
        text = " ".join((elem.text or "").split())
        cls = (elem.get_attribute("class") or "").lower()
        if "thm_box" in cls:
            continue
        if THEME_KEYWORD in text and _has_time_pattern(text):
            keyword_hits.append(elem)
    if keyword_hits:
        return keyword_hits

    # 2) 키워드가 없으면 가운데 박스 선택
    # 박스 기준 x좌표 정렬 후 theme index(기본 2번) 선택
    col = []
    for elem in uniq:
        text = " ".join((elem.text or "").split())
        cls = (elem.get_attribute("class") or "").lower()
        if "thm_box" in cls:
            continue
        if not _has_time_pattern(text):
            continue
        rect = elem.rect or {}
        col.append((float(rect.get("x") or 0), elem))
    if not col:
        return []
    col.sort(key=lambda x: x[0])
    idx = min(max(THEME_INDEX, 1), len(col)) - 1
    return [col[idx][1]]


def send_telegram(msg: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ 텔레그램 설정 없음: MY_ALARM_TOKEN / MY_CHAT_ID")
        return

    endpoint = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    try:
        req = request.Request(endpoint, data=payload, headers=headers, method="POST")
        with request.urlopen(req, timeout=10) as resp:
            print(f"📡 텔레그램 전송 결과: {resp.status}")
    except Exception as exc:
        print(f"⚠️ 텔레그램 전송 실패: {exc}")


def create_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,2200")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


def collect_slots(driver: webdriver.Chrome, target_date: str, is_holiday: bool) -> list[str]:
    url = build_url(target_date)
    print(f"🔎 접속: {url}")

    driver.get(url)
    WebDriverWait(driver, WAIT_SECONDS).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
    time.sleep(1.2)

    # 1) '향' 키워드 우선, 없으면 가운데 컬럼(2번 테마) 폴백
    containers = _pick_theme_containers(driver)
    elements = []
    for container in containers:
        # 던전 페이지 구조 기준: time_box > ul > li 가 시간 슬롯 단위
        li_slots = container.find_elements(By.CSS_SELECTOR, ".time_box ul li")
        if li_slots:
            elements.extend(li_slots)
            continue
        # 폴백
        elements.extend(container.find_elements(By.CSS_SELECTOR, ".time_box *"))

    slots = set()
    debug_lines = []

    for elem in elements:
        text_parts = []
        for attr in [
            "innerText",
            "textContent",
            "aria-label",
            "title",
            "data-time",
            "data-value",
            "value",
            "onclick",
            "href",
        ]:
            value = elem.get_attribute(attr) or ""
            if value:
                text_parts.append(value)

        text = " ".join(" ".join(text_parts).split())
        if not text:
            continue
        # 테마명 텍스트가 없는 시간 노드가 많으므로 여기서는 키워드 강제 제외

        slot_times = extract_times(text)
        if not slot_times:
            continue

        # 박스 전체 통문자열(시간이 너무 많은 노드)은 제외
        if len(slot_times) > 2:
            if DEBUG:
                debug_lines.append(f"SKIP(BULK_NODE) {','.join(slot_times[:5])} | text={text[:120]}")
            continue

        classes = elem.get_attribute("class") or ""
        disabled_attr = elem.get_attribute("disabled")
        aria_disabled = (elem.get_attribute("aria-disabled") or "").lower()

        if has_blocked_signal(text, classes, disabled_attr, aria_disabled):
            if DEBUG:
                debug_lines.append(f"BLOCKED {','.join(slot_times[:5])} | text={text} | class={classes}")
            continue

        for slot_time in slot_times:
            if not is_in_allowed_time_range(slot_time, is_holiday):
                if DEBUG:
                    debug_lines.append(f"SKIP(TIME_FILTER) {slot_time} | text={text} | class={classes}")
                continue

            # 핵심: 실제 예약 페이지로 이동 가능한 슬롯만 허용
            links = elem.find_elements(By.CSS_SELECTOR, "a[href]")
            hrefs = [((a.get_attribute("href") or "").strip()) for a in links]
            hrefs = [h for h in hrefs if h]
            has_reservation_link = any(
                ("go=rev." in h and "rev.main" not in h and "javascript:" not in h.lower())
                or ("rev.write" in h)
                or ("rev.resv" in h)
                for h in hrefs
            )

            if not has_reservation_link:
                if DEBUG:
                    debug_lines.append(
                        f"SKIP(NO_RESERVATION_LINK) {slot_time} | text={text} | class={classes} | hrefs={hrefs}"
                    )
                continue

            slots.add(slot_time)
            if DEBUG:
                debug_lines.append(f"OPEN(LINK) {slot_time} | text={text} | class={classes} | hrefs={hrefs}")

    if DEBUG:
        print("----- DEBUG SLOT CANDIDATES -----")
        print(
            f"DEBUG: theme={THEME_KEYWORD}, theme_index={THEME_INDEX}, "
            f"containers={len(containers)}, candidates={len(elements)}"
        )
        for line in debug_lines[:120]:
            print(line)
        print("----- END DEBUG -----")
        if not debug_lines:
            dump_path = os.path.abspath(f"debug_dungeon_{target_date}.html")
            with open(dump_path, "w", encoding="utf-8") as fp:
                fp.write(driver.page_source)
            print(f"DEBUG: no slot candidates, html dump saved: {dump_path}")

    return sorted(slots)


def main() -> None:
    now_kst = get_kst_now()
    open_dates = get_open_dates(now_kst)
    holiday_set = build_holiday_set(open_dates)

    date_labels = [d.strftime("%Y-%m-%d") for d in open_dates]
    print(
        f"📅 검사 기간: {date_labels[0]} ~ {date_labels[-1]} "
        f"(기준시각 KST {now_kst.strftime('%Y-%m-%d %H:%M')}, 오픈시각 {OPEN_HOUR_KST}:00)"
    )

    findings = []
    driver = create_driver()
    try:
        for target in open_dates:
            target_date = target.strftime("%Y-%m-%d")
            is_holiday = target.weekday() >= 5 or target in holiday_set
            if not is_holiday:
                if DEBUG:
                    print(f"SKIP [평일 제외] {target_date}")
                continue
            day_name = KOR_WEEKDAYS[target.weekday()]
            kind = "휴일" if is_holiday else "평일"
            print(f"🧭 확인: {target_date}({day_name}) [{kind}]")

            slots = collect_slots(driver, target_date, is_holiday)
            if not slots:
                continue

            joined = ", ".join(slots)
            print(f"✅ {target_date}({day_name}) [{kind}] -> {joined}")
            findings.append(f"- {target_date}({day_name}) [{kind}] {joined}")
    finally:
        driver.quit()

    if not findings:
        print("❌ 검사 기간 내 빈자리 없음")
        return

    msg = (
        "🔥 [던전 빈자리 발견]\n"
        f"지점: {ZIZUM_ID}\n"
        f"{chr(10).join(findings)}\n"
        f"예약: {BASE_URL}?go=rev.main&s_zizum={ZIZUM_ID}"
    )
    send_telegram(msg)


if __name__ == "__main__":
    main()
