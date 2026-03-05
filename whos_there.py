from __future__ import annotations

import json
import os
import ssl
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib import parse, request

try:
    import holidays
except ImportError:
    holidays = None

BASE_SITE = "https://www.keyescape.com"
API_URL = f"{BASE_SITE}/controller/run_proc.php"
OPEN_HOUR_KST = 22

WEEKDAY_START = "18:30"
WEEKDAY_END = "22:30"
HOLIDAY_END = "22:30"
KOR_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

TELEGRAM_TOKEN = os.environ.get("MY_ALARM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("MY_CHAT_ID")
DEBUG = os.environ.get("DEBUG_SLOT", "0") == "1"
AVAILABLE_ENABLE_VALUES = {"Y", "1", "TRUE", "T"}


@dataclass(frozen=True)
class Theme:
    name: str
    zizum_num: int
    theme_num: int
    theme_info_num: int


THEMES = [
    Theme(name="아야코", zizum_num=23, theme_num=71, theme_info_num=63),
    Theme(name="괴록", zizum_num=23, theme_num=70, theme_info_num=61),
]


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


def to_minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def is_in_allowed_time_range(slot_time: str, is_holiday: bool) -> bool:
    value = to_minutes(slot_time)
    if is_holiday:
        return value <= to_minutes(HOLIDAY_END)
    return to_minutes(WEEKDAY_START) <= value <= to_minutes(WEEKDAY_END)


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


def post_api(form: dict[str, Any]) -> dict[str, Any]:
    data = parse.urlencode(form).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": f"{BASE_SITE}/reservation1.php",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
    }
    req = request.Request(API_URL, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        if DEBUG:
            print("DEBUG: SSL verify failed, retry with unverified SSL context")
        insecure_ctx = ssl._create_unverified_context()
        with request.urlopen(req, timeout=15, context=insecure_ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def fetch_theme_date(theme: Theme) -> dict[str, Any]:
    return post_api({"t": "get_theme_date", "num": theme.theme_info_num})


def fetch_theme_times(theme: Theme, target_date: str, end_day: int) -> dict[str, Any]:
    return post_api(
        {
            "t": "get_theme_time",
            "date": target_date,
            "zizumNum": theme.zizum_num,
            "themeNum": theme.theme_num,
            "endDay": end_day,
        }
    )


def parse_open_slots(resp: dict[str, Any], is_holiday: bool) -> list[str]:
    slots = set()
    skipped_by_enable = 0
    for item in resp.get("data", []) or []:
        hh = str(item.get("hh", "")).strip().zfill(2)
        mm = str(item.get("mm", "")).strip().zfill(2)
        if not hh.isdigit() or not mm.isdigit():
            continue
        slot_time = f"{hh}:{mm}"

        # API마다 enable 표현이 달라질 수 있어 대표 키를 순차 확인한다.
        raw_enable = (
            item.get("enable", item.get("is_enable", item.get("available", item.get("use_yn", ""))))
        )
        enable = str(raw_enable).strip().upper()
        if enable not in AVAILABLE_ENABLE_VALUES:
            skipped_by_enable += 1
            continue

        if not is_in_allowed_time_range(slot_time, is_holiday):
            continue

        slots.add(slot_time)

    if DEBUG and skipped_by_enable:
        print(f"DEBUG: skipped by enable={skipped_by_enable}")

    return sorted(slots)


def check_theme_date(theme: Theme, target_date: str, is_holiday: bool) -> list[str]:
    # 사이트 로직상 endDay 파라미터가 필요한 케이스가 있어 0/1 모두 시도한다.
    first = fetch_theme_times(theme, target_date, end_day=0)
    if first.get("status"):
        return parse_open_slots(first, is_holiday)

    second = fetch_theme_times(theme, target_date, end_day=1)
    if second.get("status"):
        return parse_open_slots(second, is_holiday)

    if DEBUG:
        print(
            f"DEBUG: no status for {theme.name} {target_date} "
            f"msg0={first.get('msg')} msg1={second.get('msg')}"
        )
    return []


def reservation_url(theme: Theme) -> str:
    params = {
        "zizum_num": str(theme.zizum_num),
        "theme_num": str(theme.theme_num),
        "theme_info_num": str(theme.theme_info_num),
    }
    return f"{BASE_SITE}/reservation1.php?{parse.urlencode(params)}"


def main() -> None:
    now_kst = get_kst_now()
    open_dates = get_open_dates(now_kst)
    holiday_set = build_holiday_set(open_dates)

    date_labels = [d.strftime("%Y-%m-%d") for d in open_dates]
    print(
        f"📅 검사 기간: {date_labels[0]} ~ {date_labels[-1]} "
        f"(기준시각 KST {now_kst.strftime('%Y-%m-%d %H:%M')}, 오픈시각 {OPEN_HOUR_KST}:00)"
    )

    findings: list[str] = []

    for theme in THEMES:
        print(f"🎭 테마 검사 시작: {theme.name}")
        try:
            meta = fetch_theme_date(theme)
            if DEBUG:
                print(
                    f"DEBUG: theme meta status={meta.get('status')} "
                    f"name={meta.get('data', {}).get('name')}"
                )
        except Exception as exc:
            print(f"⚠️ [{theme.name}] 메타 조회 실패: {exc}")
            continue

        for target in open_dates:
            target_date = target.strftime("%Y-%m-%d")
            is_holiday = target.weekday() >= 5 or target in holiday_set
            day_name = KOR_WEEKDAYS[target.weekday()]
            kind = "휴일" if is_holiday else "평일"
            print(f"🧭 [{theme.name}] {target_date}({day_name}) [{kind}]")

            try:
                slots = check_theme_date(theme, target_date, is_holiday)
            except Exception as exc:
                print(f"⚠️ [{theme.name}] {target_date} 조회 실패: {exc}")
                continue

            if not slots:
                continue

            joined = ", ".join(slots)
            print(f"✅ [{theme.name}] {target_date}({day_name}) [{kind}] -> {joined}")
            findings.append(
                f"- {theme.name} {target_date}({day_name}) [{kind}] {joined} "
                f"({reservation_url(theme)})"
            )

    if not findings:
        print("❌ 검사 기간 내 빈자리 없음")
        return

    msg = "🔥 [후즈데어 빈자리 발견]\n" + "\n".join(findings)
    send_telegram(msg)


if __name__ == "__main__":
    main()
