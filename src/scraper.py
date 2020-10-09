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
# Chrome default file save directory
SAVE_TO_DIRECTORY = "/Users/armin/Downloads"
# S3 Server Bucket name
S3_BUCKET_NAME = 'datahingeinterview'

# Load .env variables
load_dotenv(verbose=True)


def awsSession():
    '''
    Helper method that creates a boto3 session with aws using the IAM
    authentication keys
    '''
    return boto3.session.Session(
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_ACCESS_SECRET_KEY'))


def setupDB():
    '''
    Sets up the MongoDB database on the local machine
    '''
    db = client['core']
    col = db['data']


def uploadToS3(filePath):
    '''
    Helper method that uploads the court document to the S3 server

    filePath : str
        the file path to the court document to be uploaded
    '''
    # Create a new aws session
    session = awsSession()
    s3_resource = session.resource('s3')
    fileDir, fileName = os.path.split(filePath)

    # Specify the bucket
    bucket = s3_resource.Bucket(S3_BUCKET_NAME)
    # Upload the file
    bucket.upload_file(
        Filename=filePath,
        Key=fileName,
        ExtraArgs={'ACL': 'public-read'}
    )

    # Returns the S3 url to the file
    s3_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{fileName}"
    return s3_url


def addToDB(row, fileName):
    '''
    Helper method that adds the current row of scraped data to the database

    row : bs4 object
        row of data from the <table/> element from the search query
    fileName : str
        name of the court file stored locally
    '''
    db = client['core']
    col = db['data']

    data = row.findAll('td')

    # Upload file to S3 and get the url
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


def populateDB():
    '''
    Scrapes the data from the website and populates the MongoDB database
    '''

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
    # Add options to allow for printing to pdf
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_experimental_option('prefs', profile)
    chrome_options.add_argument('--kiosk-printing')
    driver = webdriver.Chrome(
        chromedriverLocation,
        chrome_options=chrome_options
    )

    driver.get(url)

    # XPath for html elements in the search form
    lispendensOption = '//*[@id="document_type"]/select/option[18]'
    searchButton = '//*[@id="search_official_records"]/input'

    # Queries for Lis Pendens
    driver.find_element_by_xpath(lispendensOption).click()
    driver.find_element_by_xpath(searchButton).click()

    # Boolean for while loop
    done = False

    while not done:
        # Scrapes the current search page
        currentPage = driver.page_source
        soup = BeautifulSoup(currentPage, features="html.parser")
        table = soup.find(id='search_results1')
        body = table.find('tbody')

        # Adds each row of the table to the database
        for row in body.findAll('tr'):
            # Checks for latest file in the default save directory to be
            # compared later to establish whether the file has finished
            # downloading
            os.chdir(SAVE_TO_DIRECTORY)
            files = filter(os.path.isfile, os.listdir(SAVE_TO_DIRECTORY))
            files = [os.path.join(SAVE_TO_DIRECTORY, f)
                     for f in files]
            files.sort(key=lambda x: os.path.getmtime(x))
            latest_file = files[-1]

            # Open court document
            driver.get(
                "https://www.myfloridacounty.com/ori/image.do?instrumentNumber="
                + row.findAll('td')[6].string
            )

            # Prints current page to pdf
            driver.execute_script('window.print();')

            # Halts the program until a new file is detected (the new downloaded
            # file) by comparing the latest file in the directory
            while True:
                files = filter(os.path.isfile, os.listdir(SAVE_TO_DIRECTORY))
                files = [os.path.join(SAVE_TO_DIRECTORY, f)
                         for f in files]
                files.sort(key=lambda x: os.path.getmtime(x))
                newest_file = files[-1]

                # New file found (downloaded court document)
                if (latest_file != newest_file):
                    break

            # Renames the file according to its Instrument Number
            courtFileName = row.findAll('td')[6].string+".pdf"
            os.rename(newest_file, courtFileName)
            # Add the scraped data and court file to the database
            addToDB(row, courtFileName)
            # Remove the file from the local machine
            os.remove(f"{SAVE_TO_DIRECTORY}/{courtFileName}")
            # Navigate back to the main search queries
            driver.back()

        # Proceed to the next page
        try:
            driver.find_element_by_xpath("//*[text() = 'Next']").click()
        # Next page does not exist, terminate the loop
        except:
            print("Done :)")
            done = True


# Setup the local database and then finally scrape the website and populate the
# database
setupDB()
populateDB()
