import time
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
import requests

# --- [사용자 설정구역] ---
# 주말(토, 일) 감시 시간대
WEEKEND_TIMES = ["10:50", "12:00", "13:10", "14:20", "15:30", "16:40", "17:50", "19:00", "20:10", "21:20"]

# 평일(월~금) 감시 시간대
WEEKDAY_TIMES = ["09:40", "19:00", "20:10", "21:20"]

CHECK_INTERVAL = 15
# -----------------------

options = Options()
options.add_argument("--headless")
options.add_argument("--window-size=1920,1080")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_argument(
    "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

def get_next_week_info():
    """오늘부터 7일간의 날짜와 요일 정보를 생성"""
    day_list = []
    for i in range(7):
        target = datetime.now() + timedelta(days=i)
        # weekday(): 월요일 0 ~ 일요일 6
        is_weekend = target.weekday() >= 5
        day_list.append({
            "date": target.strftime('%Y-%m-%d'),
            "is_weekend": is_weekend
        })
    return day_list


def check_reservations():
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    day_info_list = get_next_week_info()

    try:
        driver.get("https://page-today.co.kr/#reserve")
        time.sleep(4)

        for day_info in day_info_list:
            target_date = day_info["date"]
            is_weekend = day_info["is_weekend"]
            # 요일에 맞는 타겟 시간 설정
            target_times = WEEKEND_TIMES if is_weekend else WEEKDAY_TIMES

            now_str = datetime.now().strftime('%H:%M:%S')
            day_type = "주말" if is_weekend else "평일"

            # 날짜 주입 스크립트
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
                            print(f"✅ [{now_str}] 발견: ({day_type}) {target_date} {target_time} 예약 가능!")

                            alarm_url = "http://api.noti.daumkakao.io/send/messenger/group"
                            body = {
                                "to": 24122,
                                "msg": "hi"
                            }
                            res = requests.post(alarm_url, json=body)
                            print(res.text)
                        break

    except Exception as e:
        print(f"⚠️ 에러: {e}")
    finally:
        driver.quit()


if __name__ == "__main__":
    print(f"🕵️ 요일 맞춤형 무소음 감시 시작 (오늘부터 7일간)")
    while True:
        check_reservations()
        print(f"🔄 전체 날짜 순회 완료 ({datetime.now().strftime('%H:%M:%S')})")
        time.sleep(CHECK_INTERVAL)