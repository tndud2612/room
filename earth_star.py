import json
import os
import re
import time
from datetime import date, datetime, timedelta
from urllib import request

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
BASE_URL = "https://xn--2e0b040a4xj.com/reservation"
BRANCH_ID = 2
THEME_ID = 18
WAIT_SECONDS = 12
OPEN_HOUR_KST = 22

AVAILABLE_KEYWORDS = ["예약가능", "가능", "예약하기", "빈자리", "바로예약", "신청", "가능합니다"]
BLOCKED_KEYWORDS = [
    "마감",
    "예약마감",
    "예약완료",
    "불가",
    "대기",
    "종료",
    "closed",
    "sold out",
    "soldout",
    "full",
]
WEEKDAY_START = "18:30"
WEEKDAY_END = "22:30"
HOLIDAY_END_EXCLUSIVE = "22:30"
KOR_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

TELEGRAM_TOKEN = os.environ.get("MY_ALARM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("MY_CHAT_ID")
DEBUG = os.environ.get("DEBUG_SLOT", "0") == "1"


def get_kst_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def get_kst_today() -> str:
    return get_kst_now().strftime("%Y-%m-%d")


def get_open_dates(now_kst: datetime) -> list[date]:
    # 기본은 오늘 포함 7일(오늘~+6일). 오후 10시 이후면 +7일까지 오픈.
    total_days = 8 if now_kst.hour >= OPEN_HOUR_KST else 7
    return [(now_kst.date() + timedelta(days=offset)) for offset in range(total_days)]


def build_holiday_set(open_dates: list[date]) -> set[date]:
    if holidays is None:
        raise RuntimeError(
            "공휴일 판별을 위해 holidays 패키지가 필요합니다. "
            "설치: pip install holidays"
        )
    years = sorted({d.year for d in open_dates})
    kr_holidays = holidays.country_holidays("KR", years=years)
    return set(kr_holidays.keys())


def build_url(target_date: str) -> str:
    return f"{BASE_URL}?branch={BRANCH_ID}&theme={THEME_ID}&date={target_date}#list"


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


def is_blocked_slot(
    text: str,
    classes: str,
    disabled_attr: str | None,
    aria_disabled: str,
    href: str,
    onclick: str,
) -> bool:
    lowered = text.lower()
    if disabled_attr is not None:
        return True
    if aria_disabled == "true":
        return True

    lowered_classes = classes.lower()
    if any(keyword in lowered_classes for keyword in ["sold", "close", "end", "finish"]):
        return True

    lowered_href = href.lower()
    lowered_onclick = onclick.lower()
    if "return false" in lowered_onclick:
        return True
    if any(keyword in lowered_href for keyword in ["sold", "closed", "full"]):
        return True

    return any(word in lowered for word in BLOCKED_KEYWORDS)


def is_available_slot(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in AVAILABLE_KEYWORDS)


def extract_time(text: str) -> str | None:
    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    match = re.search(r"\b([01]?\d|2[0-3])\s*시\s*([0-5]?\d)\s*분?\b", text)
    if match:
        return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"

    match = re.search(r"\b([01]?\d|2[0-3])\s*시\b", text)
    if match:
        return f"{int(match.group(1)):02d}:00"

    match = re.search(r"\b([01]\d|2[0-3])([0-5]\d)\b", text)
    if match:
        return f"{match.group(1)}:{match.group(2)}"

    return None


def to_minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def is_in_allowed_time_range(slot_time: str, is_holiday: bool) -> bool:
    value = to_minutes(slot_time)
    if is_holiday:
        # 휴일: 22:30 이하(포함)
        return value <= to_minutes(HOLIDAY_END_EXCLUSIVE)
    # 평일: 18:30~22:30 (포함)
    return to_minutes(WEEKDAY_START) <= value <= to_minutes(WEEKDAY_END)


def check_empty_slots(target_date: str, is_holiday: bool) -> list[str]:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    url = build_url(target_date)
    print(f"🔎 접속: {url}")

    try:
        driver.get(url)
        WebDriverWait(driver, WAIT_SECONDS).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#list"))
        )
        time.sleep(1)

        selectors = [
            "#list button",
            "#list a",
            "#list li",
            "#list .item",
            "#list .schedule",
            "#list .list-group-item",
            "#list [onclick]",
            "#list .time",
            "#list *",
            ".time",
            "[class*='time']",
            "[id*='time']",
        ]

        elements = []
        for selector in selectors:
            found = driver.find_elements(By.CSS_SELECTOR, selector)
            if found:
                elements.extend(found)
        if DEBUG:
            print(f"DEBUG: selector candidates={len(elements)}")

        if not elements:
            elements = driver.find_elements(By.CSS_SELECTOR, "body *")
            if DEBUG:
                print(f"DEBUG: body fallback candidates={len(elements)}")

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
            if not text.strip():
                continue

            classes = elem.get_attribute("class") or ""
            disabled_attr = elem.get_attribute("disabled")
            aria_disabled = (elem.get_attribute("aria-disabled") or "").lower()
            href = elem.get_attribute("href") or ""
            onclick = elem.get_attribute("onclick") or ""
            slot_time = extract_time(text)
            if not slot_time:
                continue

            if is_blocked_slot(text, classes, disabled_attr, aria_disabled, href, onclick):
                if DEBUG:
                    debug_lines.append(
                        f"BLOCKED {slot_time} | text={text} | class={classes} | "
                        f"aria={aria_disabled} | onclick={onclick} | href={href}"
                    )
                continue

            clickable_hint = any(
                keyword in f"{href} {onclick}".lower()
                for keyword in ["reserve", "reservation", "book", "apply", "theme", "time", "date"]
            )
            class_allows = not any(keyword in classes.lower() for keyword in ["sold", "close", "full"])
            if is_available_slot(text) or clickable_hint or class_allows:
                if not is_in_allowed_time_range(slot_time, is_holiday):
                    if DEBUG:
                        reason = "HOLIDAY_TIME_FILTER" if is_holiday else "WEEKDAY_TIME_FILTER"
                        debug_lines.append(
                            f"SKIP({reason}) {slot_time} | text={text} | class={classes}"
                        )
                    continue
                slots.add(slot_time)
                if DEBUG:
                    debug_lines.append(
                        f"OPEN {slot_time} | text={text} | class={classes} | "
                        f"aria={aria_disabled} | onclick={onclick} | href={href}"
                    )
            elif DEBUG:
                debug_lines.append(
                    f"SKIP {slot_time} | text={text} | class={classes} | "
                    f"aria={aria_disabled} | onclick={onclick} | href={href}"
                )

        if DEBUG:
            print("----- DEBUG SLOT CANDIDATES -----")
            for line in debug_lines[:120]:
                print(line)
            print("----- END DEBUG -----")
            source = driver.page_source
            source_time_hits = re.findall(
                r"(?:[01]?\d|2[0-3]):[0-5]\d|(?:[01]?\d|2[0-3])\s*시\s*(?:[0-5]?\d)\s*분?",
                source,
                flags=re.IGNORECASE,
            )
            print(f"DEBUG: page_source time-pattern hits={len(source_time_hits)}")
            if source_time_hits:
                print(f"DEBUG: sample hits={sorted(set(source_time_hits))[:20]}")
            if not debug_lines:
                dump_path = os.path.abspath(f"debug_{BRANCH_ID}_{THEME_ID}_{target_date}.html")
                with open(dump_path, "w", encoding="utf-8") as fp:
                    fp.write(source)
                print(f"DEBUG: no slot candidates, html dump saved: {dump_path}")

        return sorted(slots)
    finally:
        driver.quit()


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
    for target in open_dates:
        target_date = target.strftime("%Y-%m-%d")
        is_holiday = target.weekday() >= 5 or target in holiday_set
        day_name = KOR_WEEKDAYS[target.weekday()]
        kind = "휴일" if is_holiday else "평일"
        print(f"🧭 확인: {target_date}({day_name}) [{kind}]")
        empty_slots = check_empty_slots(target_date, is_holiday=is_holiday)
        if empty_slots:
            findings.append((target_date, day_name, kind, empty_slots))

    if findings:
        lines = []
        for target_date, day_name, kind, slots in findings:
            joined = ", ".join(slots)
            lines.append(f"- {target_date}({day_name}) [{kind}] {joined}")
            print(f"✅ {target_date}({day_name}) [{kind}] -> {joined}")

        msg = (
            f"🔥 [방탈출 빈자리 발견]\n"
            f"지점/테마: {BRANCH_ID}/{THEME_ID}\n"
            f"{chr(10).join(lines)}\n"
            f"예약: {BASE_URL}?branch={BRANCH_ID}&theme={THEME_ID}#list"
        )
        send_telegram(msg)
    else:
        print("❌ 검사 기간 내 빈자리 없음")


if __name__ == "__main__":
    main()
