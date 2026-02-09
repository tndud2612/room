import time
import os
import requests
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

# --- [설정] ---
WEEKEND_TIMES = ["10:50", "12:00", "13:10", "14:20", "15:30", "16:40", "17:50", "19:00", "20:10", "21:20"]
WEEKDAY_TIMES = ["10:50", "12:00", "13:10", "14:20", "15:30", "16:40", "17:50", "19:00", "20:10", "21:20"]

TELEGRAM_TOKEN = os.environ.get('MY_ALARM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('MY_CHAT_ID')


def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ 텔레그램 설정 확인 필요")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        res = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
        print(f"📡 알람 전송 결과: {res.status_code}")
    except Exception as e:
        print(f"⚠️ 전송 에러: {e}")


def get_next_week_info():
    day_list = []
    # 한국 요일 이름 리스트
    weekdays = ['월', '화', '수', '목', '금', '토', '일']

    for i in range(7):
        target = datetime.utcnow() + timedelta(hours=9) + timedelta(days=i)
        day_list.append({
            "date": target.strftime('%Y-%m-%d'),
            "day_name": weekdays[target.weekday()],  # 요일 추출
            "is_weekend": target.weekday() >= 5
        })
    return day_list


def check_reservations():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    day_info_list = get_next_week_info()

    print(f"🕵️ 감시 시작: {day_info_list[0]['date']} ~ {day_info_list[-1]['date']}")

    try:
        driver.get("https://page-today.co.kr/#reserve")
        time.sleep(7)

        for day_info in day_info_list:
            target_date = day_info["date"]
            day_name = day_info["day_name"]
            target_times = WEEKEND_TIMES if day_info["is_weekend"] else WEEKDAY_TIMES

            print(f"📅 확인 중: {target_date}({day_name})")

            # 날짜 변경 JS
            update_script = f"""
            var date = '{target_date}';
            var dpEl = document.getElementById('datepicker');
            if(dpEl) dpEl.value = date;
            if (window.jQuery && $('#datepicker').data('datepicker')) {{
                $('#datepicker').datepicker('setDate', date);
                $('#datepicker').datepicker('update');
            }}
            if (dpEl) dpEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
            if (typeof get_theme_list === 'function') {{ get_theme_list(date); }}
            """
            driver.execute_script(update_script)
            time.sleep(3)

            buttons = driver.find_elements(By.TAG_NAME, "button")
            for target_time in target_times:
                for btn in buttons:
                    btn_text = btn.get_attribute("innerText").replace('\n', ' ').strip()
                    if target_time in btn_text:
                        classes = btn.get_attribute("class")
                        is_disabled = btn.get_attribute("disabled")
                        if "btn-primary" in classes and is_disabled is None:
                            print(f"✅ 발견: {target_date}({day_name}) {target_time}")

                            # 요일 포함 알람 메시지
                            msg = f"🔥 [방탈출 발견!] 🔥\n날짜: {target_date}({day_name})\n시간: {target_time}\n예약: https://page-today.co.kr/#reserve"
                            send_telegram(msg)
                        break
    except Exception as e:
        print(f"⚠️ 에러: {e}")
    finally:
        driver.quit()


if __name__ == "__main__":
    check_reservations()
