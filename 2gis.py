import time
import csv
import os
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from urllib.parse import quote

# --- НАСТРОЙКИ ---
SEARCH_QUERY = "рестораны"
CITY = "moscow"  # Важно: используйте транслит (moscow, spb, novosibirsk и т.д.)
OUTPUT_FILE = "2gis_results.csv"
# -----------------

# --- СЕЛЕКТОРЫ (проверены и актуальны) ---
SCROLL_PANEL_SELECTOR = 'div[class*="_1rkbbi0"]'
# Ищем саму ссылку внутри карточки
COMPANY_LINK_SELECTOR = 'a[href*="/firm/"]'
# Заголовок в детальном виде (используется для ожидания)
DETAILED_VIEW_HEADER_SELECTOR = 'h1' 

def setup_driver():
    """Настраивает и возвращает "незаметный" экземпляр веб-драйвера Chrome."""
    print("Инициализация undetected_chromedriver...")
    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36')
    
    driver = uc.Chrome(options=options)
    driver.implicitly_wait(10)
    return driver

def perform_search(driver, city, query):
    """Формирует URL и переходит на страницу поиска."""
    encoded_query = quote(query)
    search_url = f"https://2gis.ru/{city}/search/{encoded_query}"
    print(f"Открываю страницу: {search_url}")
    driver.get(search_url)
    return search_url

def scroll_to_end(driver):
    """Динамически прокручивает список до самого конца, пока подгружаются новые карточки."""
    print("Начинаю прокрутку списка до конца...")
    try:
        scroll_panel = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, SCROLL_PANEL_SELECTOR))
        )
        
        last_card_count = 0
        attempts = 0
        while attempts < 3: # Сделаем 3 попытки после того, как счетчик перестал меняться
            current_card_count = len(driver.find_elements(By.CSS_SELECTOR, COMPANY_LINK_SELECTOR))
            
            if current_card_count == last_card_count:
                attempts += 1
                print(f"  Количество ссылок не изменилось. Попытка {attempts}/3")
            else:
                attempts = 0 # Сбрасываем счетчик, если нашли новые ссылки

            last_card_count = current_card_count
            driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", scroll_panel)
            time.sleep(3) # Пауза для подгрузки новых карточек
        
        print(f"Прокрутка завершена. Итоговое количество ссылок: {last_card_count}")

    except Exception as e:
        print(f"Не удалось найти панель для прокрутки или произошла ошибка: {e}")

def scrape_data(driver):
    """Основной цикл скрейпинга."""
    
    print("Ожидание загрузки страницы...")
    time.sleep(3)
    
    try:
        print("Ожидание видимости первой карточки...")
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, COMPANY_LINK_SELECTOR))
        )
        print("Список компаний успешно загружен.")
    except Exception:
        print("Не удалось загрузить список компаний. Пожалуйста, проверьте интернет-соединение или перезапустите скрипт.")
        return []

    scroll_to_end(driver)

    # ЭТАП 1: Собираем все уникальные ссылки
    links = driver.find_elements(By.CSS_SELECTOR, COMPANY_LINK_SELECTOR)
    company_urls = sorted(list(set([link.get_attribute('href') for link in links if link.get_attribute('href')])))
    
    if not company_urls:
        print("Не найдено ни одной ссылки на компании после прокрутки.")
        return []
    
    print(f"Найдено {len(company_urls)} уникальных ссылок для обработки.")
    all_data = []

    # ЭТАП 2: Последовательно переходим по каждой ссылке и собираем данные
    for i, url in enumerate(company_urls):
        try:
            clean_url = url.split('?')[0]
            print(f"[{i+1}/{len(company_urls)}] Открываю: {clean_url}")
            driver.get(url)
            
            WebDriverWait(driver, 20).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, DETAILED_VIEW_HEADER_SELECTOR))
            )
            time.sleep(1.5)

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            data = {
                'name': get_text(soup, 'h1'),
                'address': get_text(soup, 'a[data-testid="address-link"]'),
                'website': get_website_link(soup),
                'phone': get_phone(soup),
                'link': clean_url,
                'rating': get_rating(soup),
                'hours': get_hours(soup)
            }
            
            print(f"    -> Собрана информация: Имя: {data['name']}, Адрес: {data['address']}, Телефон: {data['phone']}, Сайт: {data['website']}, Рейтинг: {data['rating']}, Часы: {data['hours']}")
            all_data.append(data)

        except Exception as e:
            print(f"    -> Произошла ошибка при обработке ссылки {url}: {type(e).__name__} - {e}")
            continue # Просто переходим к следующей ссылке
    
    return all_data

# --- Функции-помощники для извлечения данных ---
def get_text(soup, selector):
    """Безопасно извлекает текст из элемента по CSS селектору."""
    try:
        element = soup.select_one(selector)
        return element.get_text(strip=True) if element else "Не указано"
    except Exception:
        return "Не указано"

def get_website_link(soup):
    """Ищет ссылку на веб-сайт в детальной карточке."""
    try:
        # Ищем по testid, это самый надежный способ
        element = soup.select_one('a[data-testid="website-link"]')
        if element and element.has_attr('href'):
            return element['href']
        # Запасной вариант: ищем блок с текстом "Веб-сайт"
        website_title_element = soup.find(lambda tag: tag.name == 'div' and 'Веб-сайт' in tag.text and tag.has_attr('class') and tag['class'][0].startswith('_13eh3hv'))
        if website_title_element:
            # Ищем родительский контейнер и в нем ссылку
            parent_container = website_title_element.find_parent('div', class_=lambda c: c and c.startswith('_b0ke8'))
            if parent_container:
                link_tag = parent_container.select_one('a')
                if link_tag and link_tag.has_attr('href'):
                    return link_tag['href']
    except Exception:
        pass
    return "Не указано"


def get_phone(soup):
    """Ищет номер телефона. На 2ГИС он часто виден сразу."""
    # Этот селектор стабилен для кнопки/блока телефона.
    try:
        phone_container = soup.select_one('a[data-testid="contacts-phone-link"]')
        if phone_container:
            # Внутри контейнера ищем тег <b> с нужным классом
            phone_number_element = phone_container.select_one('b[class*="_20m50x1"]')
            if phone_number_element:
                return phone_number_element.get_text(strip=True)
    except Exception:
        pass
    return "Не указано"


def get_rating(soup):
    """Собирает рейтинг и количество отзывов."""
    try:
        # Общий контейнер для рейтинга
        rating_container = soup.select_one('div[class*="_1az2g0c"]')
        if not rating_container:
            return "Нет рейтинга"

        rating_value = "Не указано"
        review_count_text = "0 оценок"

        # Извлекаем значение рейтинга
        rating_value_element = rating_container.select_one('div[class*="_y10azs"]')
        if rating_value_element:
            rating_value = rating_value_element.get_text(strip=True)

        # Извлекаем количество отзывов
        review_count_element = rating_container.select_one('div[class*="_jspzdm"]')
        if review_count_element:
            review_count_text = review_count_element.get_text(strip=True)

        if rating_value != "Не указано":
            return f"{rating_value} ({review_count_text})"
    except Exception:
        pass
    return "Нет рейтинга"

def get_hours(soup):
    """Собирает часы работы."""
    # Этот селектор находит текст статуса (напр. "Круглосуточно", "Закрыто до завтра")
    try:
        hours_element = soup.select_one('div[class*="_d9xlex"]')
        if hours_element:
            return hours_element.get_text(strip=True)
    except Exception:
        pass
    return "Не указано"

def save_to_csv(data, filename):
    """Сохраняет собранные данные в CSV файл."""
    if not data:
        print("Нет данных для сохранения.")
        return
    
    keys = data[0].keys()
    with open(filename, 'w', newline='', encoding='utf-8') as output_file:
        dict_writer = csv.DictWriter(output_file, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(data)
    print(f"\nУспех! Данные сохранены в файл {filename}")

if __name__ == "__main__":
    driver = setup_driver()
    if driver:
        try:
            initial_url = perform_search(driver, CITY, SEARCH_QUERY)
            scraped_data = scrape_data(driver)
            save_to_csv(scraped_data, OUTPUT_FILE)
        finally:
            print("Завершение работы драйвера.")
            driver.quit()

