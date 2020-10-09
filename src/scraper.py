from selenium import webdriver
from bs4 import BeautifulSoup
import pymongo
import os
import boto3
import requests
import json
from dotenv import load_dotenv

# Connects pymongo to local mongodb client
client = pymongo.MongoClient()

# Chrome Driver for Selenium
chromedriverLocation = "./chromedriver"
# URL to be scraped
url = "https://www.myfloridacounty.com/ori/search.do?validentry=yes&skipsearch=yes&county=12"
SAVE_TO_DIRECTORY = "/Users/armin/Downloads"

S3_BUCKET_NAME = 'datahingeinterview'

load_dotenv(verbose=True)


def awsSession():
    return boto3.session.Session(
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_ACCESS_SECRET_KEY'))


# Initial setup of database in local client

def setupDB():
    db = client['core']
    col = db['data']


def uploadToS3(filePath):
    session = awsSession()
    s3_resource = session.resource('s3')
    fileDir, fileName = os.path.split(filePath)

    bucket = s3_resource.Bucket(S3_BUCKET_NAME)
    bucket.upload_file(
        Filename=filePath,
        Key=fileName,
        ExtraArgs={'ACL': 'public-read'}
    )

    s3_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{fileName}"
    return s3_url


# Helper method to add the scraped row of data onto the databse


def addToDB(row, fileName):
    db = client['core']
    col = db['data']

    data = row.findAll('td')

    s3URL = uploadToS3(f"{SAVE_TO_DIRECTORY}/{fileName}")

    # Populating the BSON
    entry = {
        'plaintiff': data[1].string,
        'defendant': data[2].string,
        'date': data[3].string,
        'document_type': data[4].string,
        'county': data[5].string,
        'instrument_num': data[6].string,
        'book_page': data[7].string,
        'pages': data[8].string,
        'description': data[9].contents[0],
        'document': s3URL
    }

    # Insert the document into the database
    col.insert_one(entry)


# Scrapes the website and populates the database accordingly

def populateDB():
    # Initialize Selenium driver

    appState = {
        "recentDestinations": [
            {
                "id": "Save as PDF",
                "origin": "local"
            }
        ],
        "selectedDestinationId": "Save as PDF",
        "version": 2
    }

    profile = {
        'printing.print_preview_sticky_settings.appState': json.dumps(appState)}

    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_experimental_option('prefs', profile)
    chrome_options.add_argument('--kiosk-printing')
    driver = webdriver.Chrome(chromedriverLocation,
                              chrome_options=chrome_options)

    driver.get(url)

    # XPath for html elements in the search form
    lispendensOption = '//*[@id="document_type"]/select/option[18]'
    searchButton = '//*[@id="search_official_records"]/input'

    # Queries for Lis Pendens
    driver.find_element_by_xpath(lispendensOption).click()
    driver.find_element_by_xpath(searchButton).click()

    # Boolean for while loop
    done = False
    i = 1
    while not done:
        # Scrapes the current search page
        currentPage = driver.page_source
        soup = BeautifulSoup(currentPage, features="html.parser")
        table = soup.find(id='search_results1')
        body = table.find('tbody')

        # Adds each row of the table to the database
        for row in body.findAll('tr'):

            if i < 100:
                i += 1
                continue

            os.chdir(SAVE_TO_DIRECTORY)
            files = filter(os.path.isfile, os.listdir(SAVE_TO_DIRECTORY))
            files = [os.path.join(SAVE_TO_DIRECTORY, f)
                     for f in files]
            files.sort(key=lambda x: os.path.getmtime(x))
            latest_file = files[-1]

            print("Opening " + str(i))
            driver.get(
                "https://www.myfloridacounty.com/ori/image.do?instrumentNumber="+row.findAll('td')[6].string)

            print("Saving " + str(i))
            driver.execute_script('window.print();')

            while True:
                files = filter(os.path.isfile, os.listdir(SAVE_TO_DIRECTORY))
                files = [os.path.join(SAVE_TO_DIRECTORY, f)
                         for f in files]
                files.sort(key=lambda x: os.path.getmtime(x))
                newest_file = files[-1]

                if (latest_file != newest_file):
                    break

            print("saved " + str(i))
            courtFileName = row.findAll('td')[6].string+".pdf"
            os.rename(newest_file, courtFileName)
            addToDB(row, courtFileName)
            os.remove(f"{SAVE_TO_DIRECTORY}/{courtFileName}")
            driver.back()

            i += 1

        # Proceed to the next page
        try:
            driver.find_element_by_xpath("//*[text() = 'Next']").click()
        # Next page does not exist, terminate the loop
        except:
            done = True


setupDB()
populateDB()
