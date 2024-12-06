import os
import boto3
import feedparser
import json
import logging
from typing import List
from urllib.parse import urlparse


if os.getenv("AWS_LAMBDA_FUNCTION_NAME") is None:
    from dotenv import load_dotenv

    load_dotenv()
    local = True


RSS_FEED_URLS = os.environ["RSS_FEED_URLS"]
BUCKET_NAME = os.environ["BUCKET_NAME"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]

NOTIFICATION_SUBJECT = "New RSS Feed Entries"

s3 = boto3.client("s3")
sns = boto3.client("sns")

logger = logging.getLogger(__name__)
if logger.handlers:
    for handler in logger.handlers:
        logger.removeHandler(handler)

logFormat = "%(asctime)s %(name)s %(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=logFormat)


def handler(event: dict, context: dict):
    process_feeds()


def process_feeds():
    feeds = [url for url in RSS_FEED_URLS.split(";")]
    for feed in feeds:
        process_feed(feed)


def process_feed(feed: str) -> str:
    try:
        logger.info(f"Processing feed {feed}")
        feed_file_key = create_feed_file_key(feed)
        feed = feedparser.parse(feed)
        current_entries: List[dict] = feed.entries
        old_entries = get_old_entries(feed_file_key)
        update_old_entries(current_entries, feed_file_key)
        if not old_entries:
            logger.info("Feed entries initialized")
            return
        old_entry_ids = [entry["id"] for entry in old_entries]
        new_entries = [
            create_text(entry)
            for entry in current_entries
            if entry["id"] not in old_entry_ids
        ]
        if new_entries:
            message = "\n".join(new_entries)
            if local:
                logger.info(message)
            else:
                send_notification(message)
        else:
            logger.info("No new entries")
    except Exception:
        logger.exception(f"Error processing feed {feed}")


def send_notification(message: str):
    try:
        logger.info("Publishing notification")
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=NOTIFICATION_SUBJECT,
            Message=message,
        )
    except Exception:
        logger.exception("Error publishing notification")


def create_text(entry: dict) -> str:
    title = entry.get("title", None)
    link = entry.get("link", None)
    return f"Title: {title}\nLink: {link}\n"


def create_feed_file_key(url: str) -> str:
    domain = urlparse(url).netloc
    return f"""{domain.replace(".", "")}.json"""


def get_old_entries(key: str) -> List[dict]:
    try:
        logger.info(f"Getting object {key}")
        response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))
        return data.get("entries", [])
    except s3.exceptions.NoSuchKey:
        logger.warning(f"Object {key} not found")
        return []
    except Exception:
        logger.exception(f"Error getting object {key}")


def update_old_entries(entries: List[dict], key: str):
    try:
        logger.info(f"Updating object {key}")
        data = json.dumps({"entries": entries})
        s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=data)
    except Exception:
        logger.exception(f"Error updating object {key}")


if __name__ == "__main__":
    process_feeds()
