import streamlit as st
import json
import os
import pandas as pd
import re
import sys
sys.path.append(os.path.abspath('../scripts/helper_scripts'))
from scripts.helper_scripts import *
import time
import tldextract
import urllib.parse
import warnings
warnings.simplefilter(action='ignore', category=pd.errors.PerformanceWarning)
warnings.simplefilter(action='ignore', category=UserWarning)
warnings.simplefilter(action='ignore', category=FutureWarning)

from bs4 import BeautifulSoup
from collections import defaultdict
from stqdm import stqdm
from zenrows import ZenRowsClient

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium_stealth import stealth

def extract_revenue_method1(html):
        soup = BeautifulSoup(html, 'html.parser')
        div = soup.find('div', {'class': 'company-statistics-v2 REVENUE_EXACT CP'})
        if div:
            revenue_div = div.find('div', {'class': 'count-container REVENUE_EXACT CP botifyrevenuedata'})
            if revenue_div:
                return revenue_div.text.replace("Upgrade to Pro to unlock exact revenue data", "")
        return None
def extract_revenue_method2(html):
    try:
        soup = BeautifulSoup(html, 'html.parser')
        next_data_div = soup.find('script', {'id': '__NEXT_DATA__'})
        if next_data_div:
            summary_section = next_data_div.get_text()
            try:
                data_json = json.loads(summary_section)
            except json.JSONDecodeError as e:
                return None
            match = re.search(r'estimated annual revenue of ([\d.]+[KkMmBb])', summary_section)
            if match:
                return match.group(1)
        return None
    except Exception as e:
        return None
def extract_revenue_method3(html):
    try:
        soup = BeautifulSoup(html, 'html.parser')
        next_data_script = soup.find('script', {'id': '__NEXT_DATA__'})    
        if next_data_script and next_data_script.string:        
            try:
                data = json.loads(next_data_script.string, object_hook=lambda d: defaultdict(lambda: None, d))
            except json.JSONDecodeError as e:
                return None
            formatted_revenue = data['props']['initialState'].get('formattedRevenue')            
            if formatted_revenue:
                return '$' + formatted_revenue
            else:
                return formatted_revenue        
        return None
    except Exception as e:
        return None
def extract_website(html):
    soup = BeautifulSoup(html, 'html.parser')
    a = soup.find('a', {'class': 'cp-link link primary'})
    if a:
        return a['href']
    return None
def extract_domain(text):
    try:
        return tldextract.extract(text).registered_domain
    except Exception:
        return None
def search_owler_urls(OWLER_PC_cookie, dataframe, column_name, streamlit_execution=False):
    dataframe.drop_duplicates(subset=[column_name], inplace=True)
    dataframe_search_results = pd.DataFrame(columns=[column_name, 'Owler URL', 'Company name'])
    driver = get_driver()
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            )
    driver.get("https://www.google.com/?hl=en")
    time.sleep(5)    
    try:
        accept_all_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[.//div[text()='Accept all'] or .//span[text()='Accept all']]"))
        )
        accept_all_button.click()
    except:
        pass
    search_box = driver.find_element(By.NAME, 'q')
    search_box.send_keys('owler.com')
    search_box.send_keys(Keys.RETURN)
    time.sleep(5)    
    first_result = driver.find_element(By.CSS_SELECTOR, 'h3')
    first_result.click()
    time.sleep(5)    
    try:
        host_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "usercentrics-root"))
        )    
        button = driver.execute_script("""
            var hostElement = arguments[0];
            var shadowRoot = hostElement.shadowRoot;
            if (shadowRoot) {
                return shadowRoot.querySelector('button[data-testid="uc-accept-all-button"]');
            } else {
                return null;
            }
        """, host_element)
        if button is not None:
            driver.execute_script("arguments[0].click();", button)
    except Exception as e:
        print(f"Error while trying to click the accept-all button: {e}")
    time.sleep(5)
    cookie = {'name': 'OWLER_PC', 'value': OWLER_PC_cookie}
    driver.add_cookie(cookie)
    driver.refresh()
    time.sleep(5)
    driver.get("https://www.owler.com/feed")
    time.sleep(10)
    for url in stqdm(dataframe[column_name]):
        time.sleep(2)
        try:
            time.sleep(1.5)
            searchbar_input = driver.find_element(By.XPATH, '//input[@class="searchbar-input"]')
            driver.execute_script("arguments[0].value = '';", searchbar_input)
            searchbar_input.send_keys(url)
            time.sleep(2)
            a_element = driver.find_element(By.XPATH, '//a[@class="company-link content-company-link"]')
            owler_url = a_element.get_attribute('href')
            company_name = a_element.find_element(By.XPATH, './/span[@class="company-name"]').text
            temporal_search_results_dataframe = pd.DataFrame({column_name: [url], 'Owler URL': [owler_url], 'Company name': [company_name]})
            dataframe_search_results = pd.concat([dataframe_search_results, temporal_search_results_dataframe])
        except Exception:
            pass
    return dataframe_search_results

def scraping_owler_urls(dataframe_search_results, domainColumnName, zenrowsApiKey, owlerColumnName, streamlit_execution=False):
    dataframe_search_results.drop_duplicates(subset=[domainColumnName], inplace=True)
    dataframe_scrape_results = pd.DataFrame(columns=['Owler URL', 'Redirected URL' ,'Revenue range', 'Revenue 1', 'Revenue 2', 'Owler website', 'Owler domain'])
    client = ZenRowsClient(zenrowsApiKey)
    print("ZenRows - Before execution")
    check_zenrows_usage(zenrowsApiKey, streamlit_execution=False)
    owler_urls = dataframe_search_results[owlerColumnName].tolist()
    owler_urls = [owler_urls[i] for i in range(len(owler_urls)) if owler_urls[i] not in owler_urls[:i]]
    def fetch_url(client, url, params=None):
        response = client.get(url, params=params) if params else client.get(url)
        return response
    for url_scape in stqdm(owler_urls):
        response = fetch_url(client, url_scape)
        if not response or response.status_code != 200:
            response = fetch_url(client, url_scape, params={"js_render": "true"})
        if not response or response.status_code != 200:
            response = fetch_url(client, url_scape, params={"js_render": "true", "premium_proxy": "true"})
        if response and response.status_code == 200:
            html_content = response.text
            redirected_url = response.url
            redirected_url = urllib.parse.unquote(re.search(r"https://api\.zenrows\.com/v1/\?url=(.*)&apikey=", redirected_url).group(1)) if redirected_url and re.search(r"https://api\.zenrows\.com/v1/\?url=(.*)&apikey=", redirected_url) else None
            revenue_range = extract_revenue_method1(html_content)
            exact_revenue_1 = extract_revenue_method2(html_content)
            exact_revenue_2 = extract_revenue_method3(html_content)
            owler_website = extract_website(html_content)
            owler_domain = extract_domain(owler_website)
            owler_domain = owler_domain.lower() if owler_domain is not None else None
            temporal_scrape_results_dataframe = pd.DataFrame({'Owler URL': [url_scape], 'Redirected URL': [redirected_url], 'Revenue range': [revenue_range], 'Revenue 1': [exact_revenue_1], 'Revenue 2': [exact_revenue_2], 'Owler website': [owler_website], 'Owler domain': [owler_domain]})
            dataframe_scrape_results = pd.concat([dataframe_scrape_results, temporal_scrape_results_dataframe])
    dataframe_results = dataframe_search_results.merge(dataframe_scrape_results, left_on=owlerColumnName, right_on='Owler URL')
    dataframe_results['EQ'] = (dataframe_results[domainColumnName].str.lower() == dataframe_results['Owler domain'].str.lower())
    print("ZenRows - After execution")
    check_zenrows_usage(zenrowsApiKey, streamlit_execution=False)
    return dataframe_results
