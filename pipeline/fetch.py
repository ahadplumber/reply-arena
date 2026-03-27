"""Fetch all replies to the target tweet via X API v2."""
import requests
from config import X_BEARER_TOKEN, TWEET_ID

API_URL = "https://api.x.com/2/tweets/search/recent"
HEADERS = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}

TWEET_FIELDS = "created_at,public_metrics,text,author_id,in_reply_to_user_id,entities,attachments"
USER_FIELDS = "name,username,description,public_metrics,profile_image_url,verified"
MEDIA_FIELDS = "type,url,preview_image_url"
EXPANSIONS = "author_id,attachments.media_keys"


def fetch_all_replies() -> dict:
    """Fetch all replies, paginating through results. Returns combined data."""
    all_tweets = []
    all_users = {}
    all_media = {}
    next_token = None

    while True:
        params = {
            "query": f"conversation_id:{TWEET_ID}",
            "max_results": 100,
            "tweet.fields": TWEET_FIELDS,
            "user.fields": USER_FIELDS,
            "media.fields": MEDIA_FIELDS,
            "expansions": EXPANSIONS,
        }
        if next_token:
            params["next_token"] = next_token

        resp = requests.get(API_URL, headers=HEADERS, params=params)
        resp.raise_for_status()
        data = resp.json()

        if "data" in data:
            all_tweets.extend(data["data"])
        if "includes" in data:
            for user in data["includes"].get("users", []):
                all_users[user["id"]] = user
            for media in data["includes"].get("media", []):
                all_media[media["media_key"]] = media

        next_token = data.get("meta", {}).get("next_token")
        if not next_token:
            break

    # Attach user data and media to each tweet
    for tweet in all_tweets:
        tweet["author"] = all_users.get(tweet["author_id"], {})
        media_keys = tweet.get("attachments", {}).get("media_keys", [])
        tweet["media"] = [all_media[mk] for mk in media_keys if mk in all_media]

    return {"tweets": all_tweets, "total": len(all_tweets)}


if __name__ == "__main__":
    result = fetch_all_replies()
    print(f"Fetched {result['total']} replies")
