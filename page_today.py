import time
import os
import requests
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- [설정] ---
WEEKEND_TIMES = ["10:50", "12:00", "13:10", "14:20", "15:30", "16:40", "17:50", "19:00", "20:10", "21:20"]
WEEKDAY_TIMES = ["09:40", "19:00", "20:10", "21:20"]
TELEGRAM_TOKEN = os.environ.get('MY_ALARM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('MY_CHAT_ID')


def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)


def run_check():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 15)

    try:
        driver.get("https://page-today.co.kr/#reserve")
        # 예약 섹션이 로드될 때까지 충분히 대기
        time.sleep(7)

        kst_now = datetime.utcnow() + timedelta(hours=9)

        for i in range(7):
            target_dt = kst_now + timedelta(days=i)
            target_date = target_dt.strftime('%Y-%m-%d')
            target_day = str(target_dt.day)  # 달력에서 클릭할 '일' 숫자
            is_weekend = target_dt.weekday() >= 5

            print(f"📅 확인 중: {target_date}")

            try:
                # 1. 달력 입력창 클릭해서 캘린더 띄우기
                datepicker = wait.until(EC.element_to_be_clickable((By.ID, "datepicker")))
                driver.execute_script("arguments[0].click();", datepicker)
                time.sleep(1)

                # 2. 해당 날짜(day) 버튼 찾아서 클릭 (class가 'day'인 것 중 텍스트 일치)
                days = driver.find_elements(By.CSS_SELECTOR, ".datepicker-days .day:not(.old):not(.new)")
                for d in days:
                    if d.text == target_day:
                        driver.execute_script("arguments[0].click();", d)
                        break

                # 3. 데이터 로딩 대기
                time.sleep(3)

                # 4. 버튼 감지
                buttons = driver.find_elements(By.TAG_NAME, "button")
                target_times = WEEKEND_TIMES if is_weekend else WEEKDAY_TIMES

                for target_time in target_times:
                    for btn in buttons:
                        if target_time in btn.text:
                            if "btn-primary" in btn.get_attribute("class") and btn.is_enabled():
                                msg = f"🔥 [자리발견] {target_date} {target_time}\n예약: https://page-today.co.kr/#reserve"
                                send_telegram(msg)
                                print(f"✅ 알람 발송 완료: {target_time}")
                            break
            except Exception as e:
                print(f"❌ {target_date} 처리 중 오류: {e}")
                continue

    finally:
        driver.quit()


if __name__ == "__main__":
    run_check()