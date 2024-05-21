import hashlib
import re
import time
import xml.etree.ElementTree as ET
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options


class ProductScraper:
    def __init__(self, base_url, max_items):
        self.base_url = base_url
        self.max_items = max_items
        self.driver = self.init_driver()
        self.collected_items = []

    def init_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Runs Chrome in headless mode.
        chrome_options.add_argument("--no-sandbox")  # Bypass OS security model, VERY IMPORTANT for Docker
        chrome_options.add_argument("--disable-dev-shm-usage")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver

    def scroll_page(self):
        scroll_pause_time = 0.2
        screen_height = self.driver.execute_script("return window.innerHeight")
        total_height = self.driver.execute_script("return document.body.scrollHeight")

        for i in range(0, total_height, screen_height // 4):
            self.driver.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(scroll_pause_time)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height > total_height:
                total_height = new_height

        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(scroll_pause_time)

    def generate_unique_id(self, base_id, size):
        unique_string = f"{base_id}_{size}"
        unique_id = hashlib.md5(unique_string.encode()).hexdigest()[:10]
        return unique_id

    def extract_product_info(self, card):
        base_product_data = {}
        price_div = card.find_element(By.CSS_SELECTOR, 'div[itemid]')
        item_id_link = price_div.get_attribute('itemid')

        product_id = "No ID Found"
        if item_id_link:
            product_id_full = item_id_link.split('/')[-1].split('.aspx')[0]
            item_id_numbers = re.findall(r'\d+', product_id_full)
            product_id = ''.join(item_id_numbers)

        base_product_data['item_group_id'] = product_id
        base_product_data['mpn'] = product_id
        base_product_data['gtin'] = None
        base_product_data['title'] = card.find_element(By.CSS_SELECTOR,
                                                       '[data-component="ProductCardDescription"]').text
        base_product_data['description'] = card.find_element(By.CSS_SELECTOR,
                                                             '[data-component="ProductCardDescription"]').text
        base_product_data['image_link'] = card.find_element(By.CSS_SELECTOR, 'img').get_attribute('src')
        base_product_data['link'] = card.find_element(By.CSS_SELECTOR, 'a').get_attribute('href')
        base_product_data['brand'] = card.find_element(By.CSS_SELECTOR, '[data-component="ProductCardBrandName"]').text

        try:
            price_final_element = card.find_element(By.CSS_SELECTOR, '[data-component="PriceFinal"]')
            base_product_data['price'] = price_final_element.text.strip('$').replace(',', '')
        except NoSuchElementException:
            price_element = card.find_element(By.CSS_SELECTOR, '[data-component="Price"]')
            base_product_data['price'] = price_element.text.strip('$').replace(',', '')

        hover_element = card.find_element(By.CSS_SELECTOR, 'div[data-component="ProductCardInfo"]')
        action = ActionChains(self.driver)
        action.move_to_element(hover_element).perform()

        sizes = []
        try:
            sizes_element = card.find_element(By.CSS_SELECTOR, 'p[data-component="ProductCardSizesAvailable"]')
            sizes = sizes_element.text.split(', ')
        except NoSuchElementException:
            sizes = ["Sizes not available"]

        product_variants = []
        for size in sizes:
            product_data = base_product_data.copy()
            product_data['id'] = self.generate_unique_id(product_id, size)
            product_data['size'] = size
            product_data['gender'] = 'Female'
            product_data['availability'] = 'In Stock'
            product_data['product_type'] = 'Women Home > Clothing > Dresses'
            product_data['google_product_category'] = '2271'
            product_variants.append(product_data)

        return product_variants

    def collect_product_cards(self):
        product_cards = self.driver.find_elements(By.XPATH, '//li[@data-testid="productCard"]')
        for card in product_cards:
            variants = self.extract_product_info(card)
            for variant in variants:
                self.collected_items.append(variant)
                if len(self.collected_items) >= self.max_items:
                    return

    def go_to_next_page(self):
        try:
            current_url = self.driver.current_url
            next_page_button = self.driver.find_element(By.XPATH, '//a[@data-testid="page-next"]')
            next_page_button.click()
            WebDriverWait(self.driver, 10).until(EC.url_changes(current_url))
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, '//li[@data-testid="productCard"]')))
            return True
        except (NoSuchElementException, TimeoutException):
            return False

    def save_data(self):
        rss = ET.Element('rss', version="2.0", attrib={"xmlns:g": "http://base.google.com/ns/1.0"})
        channel = ET.SubElement(rss, 'channel')
        title = ET.SubElement(channel, 'title')
        title.text = 'Farfetch Women Dresses'
        description = ET.SubElement(channel, 'description')
        description.text = 'A collection of women dresses from Farfetch.'

        for item in self.collected_items:
            item_element = ET.SubElement(channel, 'item')
            for key, value in item.items():
                tag_name = f"g:{key}"
                if key == 'price':
                    value = f"{value} USD"  # Adding currency to the price
                sub_element = ET.SubElement(item_element, tag_name)
                sub_element.text = str(value) if value else 'None'

        tree = ET.ElementTree(rss)
        tree.write('products.xml', encoding='utf-8', xml_declaration=True)

    def run(self):
        self.driver.get(self.base_url)
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, '//li[@data-testid="productCard"]')))
            while len(self.collected_items) < self.max_items:
                self.scroll_page()
                self.collect_product_cards()
                if len(self.collected_items) >= self.max_items:
                    break
                if not self.go_to_next_page():
                    break
            self.save_data()
            print(f'Total {len(self.collected_items)} products found and saved.')
        except TimeoutException as ex:
            print("Timeout while waiting for product cards to load.", ex)
        finally:
            self.driver.quit()


if __name__ == '__main__':
    scraper = ProductScraper("https://www.farfetch.com/ca/shopping/women/dresses-1/items.aspx", 120)
    scraper.run()
