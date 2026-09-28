#!/usr/bin/env python3
"""Get recent uploads and view counts. Duration alone cannot prove Shorts format."""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

API = "https://www.googleapis.com/youtube/v3/"
CHANNELS = {"B tv 뉴스": "UCQeRytUmPXlZN-tgmDnCM2w", "뉴브": "@newve_with_btvnews"}
KST = ZoneInfo("Asia/Seoul")


def api(resource, key, **params):
    url = API + resource + "?" + urllib.parse.urlencode({"key": key, **params})
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.load(response)


def stamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def duration_seconds(value):
    import re
    match = re.fullmatch(r"P(?:([0-9]+)D)?T?(?:([0-9]+)H)?(?:([0-9]+)M)?(?:([0-9]+)S)?", value)
    if not match:
        return None
    d, h, m, s = (int(x or 0) for x in match.groups())
    return d * 86400 + h * 3600 + m * 60 + s


def recent_channel(key, name, identity, cutoff, now):
    selector = {"id": identity} if identity.startswith("UC") else {"forHandle": identity}
    data = api("channels", key, part="contentDetails,snippet", **selector)
    if not data.get("items"):
        raise ValueError(f"채널 조회 실패: {name} ({identity})")
    channel = data["items"][0]
    playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page, pages = [], "", 0
    while True:
        result = api("playlistItems", key, part="snippet,contentDetails", playlistId=playlist, maxResults=50, pageToken=page)
        pages += 1
        older = False
        for item in result.get("items", []):
            published = item.get("contentDetails", {}).get("videoPublishedAt")
            video_id = item.get("contentDetails", {}).get("videoId")
            if not published or not video_id:
                continue
            if stamp(published) < cutoff:
                older = True
                continue
            if stamp(published) <= now:
                ids.append(video_id)
        page = result.get("nextPageToken", "")
        if not page or older:
            break
        if pages >= 100:
            raise RuntimeError("업로드 탐색 상한(100페이지)에 도달했습니다. 조회 기간을 줄이세요.")
    videos = []
    for start in range(0, len(ids), 50):
        result = api("videos", key, part="snippet,contentDetails,statistics", id=",".join(ids[start:start + 50]))
        for video in result.get("items", []):
            published = stamp(video["snippet"]["publishedAt"])
            if not cutoff <= published <= now:
                continue
            seconds = duration_seconds(video["contentDetails"].get("duration", ""))
            if seconds is None:
                category = "검토 필요"
            elif seconds > 180:
                category = "롱폼 후보"
            else:
                category = "쇼츠 후보(화면비·실제 Shorts 여부 수동 확인)"
            videos.append({"title": video["snippet"]["title"], "video_id": video["id"],
                           "url": "https://www.youtube.com/watch?v=" + video["id"],
                           "uploaded_kst": published.astimezone(KST).isoformat(),
                           "views": int(video.get("statistics", {}).get("viewCount", 0)),
                           "duration_seconds": seconds, "format_review": category})
    videos.sort(key=lambda item: (-item["views"], item["video_id"]))
    return {"name": name, "channel_id": channel["id"],
            "long_top3_provisional": [v for v in videos if v["format_review"] == "롱폼 후보"][:3],
            "short_top3_provisional": [v for v in videos if v["format_review"].startswith("쇼츠 후보")][:3],
            "format_review_needed": [v for v in videos if v["format_review"] == "검토 필요"],
            "recent_upload_count": len(videos)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", help="KST ISO 8601 time for reproducible runs; defaults to current time")
    args = parser.parse_args()
    key = os.environ.get("YOUTUBE_API_KEY")
    now = dt.datetime.fromisoformat(args.now).astimezone(dt.timezone.utc) if args.now else dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=7)
    output = {"as_of_kst": now.astimezone(KST).isoformat(), "uploaded_since_kst": cutoff.astimezone(KST).isoformat(),
              "metric": "현재 누적 조회수", "format_warning": "YouTube Data API 영상 길이만으로 쇼츠 여부를 확정할 수 없습니다. 공개 Shorts 페이지나 제작진 기록으로 확인하세요."}
    if not key:
        output.update({"status": "미연결", "channels": [], "message": "YOUTUBE_API_KEY가 없어 실제 조회를 하지 않았습니다."})
    else:
        output.update({"status": "조회 완료, 형식 확인 필요", "channels": [recent_channel(key, name, identity, cutoff, now) for name, identity in CHANNELS.items()]})
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (urllib.error.URLError, KeyError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "조회 실패", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
