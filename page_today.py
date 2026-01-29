import time
import os
import requests
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

# --- [사용자 설정] ---
WEEKEND_TIMES = ["10:50", "12:00", "13:10", "14:20", "15:30", "16:40", "17:50", "19:00", "20:10", "21:20"]
WEEKDAY_TIMES = ["09:40", "19:00", "20:10", "21:20"]

# GitHub Secrets에서 환경변수 읽기
TELEGRAM_TOKEN = os.environ.get('MY_ALARM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('MY_CHAT_ID')


def send_telegram(msg):
    """텔레그램 메시지 전송"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ 텔레그램 설정(Secrets)이 되어있지 않습니다.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"📡 텔레그램 전송 결과: {res.status_code}")
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")


def get_next_week_info():
    day_list = []
    kst_now = datetime.utcnow() + timedelta(hours=9)
    for i in range(7):
        target = kst_now + timedelta(days=i)
        day_list.append({
            "date": target.strftime('%Y-%m-%d'),
            "is_weekend": target.weekday() >= 5
        })
    return day_list


def run_check():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    day_info_list = get_next_week_info()

    try:
        driver.get("https://page-today.co.kr/#reserve")
        time.sleep(5)

        for day_info in day_info_list:
            target_date = day_info["date"]
            target_times = WEEKEND_TIMES if day_info["is_weekend"] else WEEKDAY_TIMES

            print(f"📅 확인 중: {target_date}")

            driver.execute_script(f"""
                var date = '{target_date}';
                var dp = $('#datepicker');
                if(dp.length) {{
                    dp.val(date).datepicker('update');
                    get_theme_list(date);
                }}
            """)
            time.sleep(3)

            buttons = driver.find_elements(By.TAG_NAME, "button")
            for target_time in target_times:
                for btn in buttons:
                    if target_time in btn.get_attribute("innerText"):
                        is_avail = "btn-primary" in btn.get_attribute("class") and btn.get_attribute("disabled") is None
                        if is_avail:
                            msg = f"🔥 [방탈출 예약 가능!] 🔥\n날짜: {target_date}\n시간: {target_time}\n링크: https://page-today.co.kr/#reserve"
                            send_telegram(msg)
                        break
    except Exception as e:
        print(f"⚠️ 에러 발생: {e}")
    finally:
        driver.quit()


if __name__ == "__main__":
    run_check()