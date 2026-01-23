import time
import os
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
import requests

# --- [설정] ---
WEEKEND_TIMES = ["10:50", "12:00", "13:10", "14:20", "15:30", "16:40", "17:50", "19:00", "20:10", "21:20"]
WEEKDAY_TIMES = ["09:40", "19:00", "20:10", "21:20"]

# 깃허브 액션(리눅스) 환경을 위한 크롬 옵션 최적화
options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument(
    "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")


def get_next_week_info():
    day_list = []
    for i in range(7):
        # 깃허브 서버 시간(UTC)을 한국 시간(KST)으로 보정 (+9시간)
        target = datetime.utcnow() + timedelta(hours=9) + timedelta(days=i)
        is_weekend = target.weekday() >= 5
        day_list.append({
            "date": target.strftime('%Y-%m-%d'),
            "is_weekend": is_weekend
        })
    return day_list


def check_reservations():
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    day_info_list = get_next_week_info()

    print(f"🕵️ 감시 시작: {day_info_list[0]['date']} ~ {day_info_list[-1]['date']}")

    try:
        driver.get("https://page-today.co.kr/#reserve")
        time.sleep(5)

        for day_info in day_info_list:
            target_date = day_info["date"]
            target_times = WEEKEND_TIMES if day_info["is_weekend"] else WEEKDAY_TIMES

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
                            print(f"✅ 발견: {target_date} {target_time}")

                            # 알람 전송
                            alarm_url = "http://api.noti.daumkakao.io/send/messenger/group"
                            body = {"to": 24122, "msg": f"방탈출 발견! {target_date} {target_time}"}
                            requests.post(alarm_url, json=body)
                        break
    except Exception as e:
        print(f"⚠️ 에러: {e}")
    finally:
        driver.quit()


if __name__ == "__main__":
    # 한 번만 실행하고 종료
    check_reservations()
    print("🔄 체크 완료. 프로그램을 종료합니다.")