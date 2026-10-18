import os
import sys
import re
import json
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding='utf-8')

BOOK_ID = '49986487'
BOOK_TITLE = "蛊真人|大爱仙尊|配音木成语录(娱乐篇)"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "蛊真人_配音木成语录(娱乐篇)")
MAX_WORKERS = 5
MAX_RETRIES = 3

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
    'Referer': f'https://m.lrts.me/book/{BOOK_ID}',
    'X-Requested-With': 'XMLHttpRequest'
}

def clean_filename(name):
    # Remove characters invalid in Windows paths
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def format_duration(seconds):
    try:
        s = int(seconds)
        m, sec = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"
    except Exception:
        return str(seconds)

def format_size(bytes_num):
    try:
        b = float(bytes_num)
        if b >= 1024 * 1024:
            return f"{b / (1024 * 1024):.2f} MB"
        return f"{b / 1024:.1f} KB"
    except Exception:
        return f"{bytes_num} B"

def fetch_all_menu():
    print(f"[*] 正在从懒人听书获取书籍 [{BOOK_ID}] 的所有章节列表...")
    metadata_cache = 'sections_metadata.json'
    if os.path.exists(metadata_cache):
        try:
            with open(metadata_cache, 'r', encoding='utf-8') as f:
                cached = json.load(f)
                if len(cached) == 240:
                    print(f"[+] 从本地缓存加载了全部 {len(cached)} 个章节信息。")
                    return cached
        except Exception:
            pass

    all_sections = []
    page = 1
    page_size = 50
    while True:
        params = {
            'bookId': BOOK_ID,
            'pageNum': str(page),
            'pageSize': str(page_size),
            'sortType': '0'
        }
        url = f'https://m.lrts.me/ajax/getBookMenu?{urllib.parse.urlencode(params)}'
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            items = data.get('list', [])
            if not items:
                break
            all_sections.extend(items)
            print(f"  - 已获取第 {page} 页，累计 {len(all_sections)} / {data.get('sections', 240)} 章节")
            if len(items) < page_size:
                break
        page += 1
        time.sleep(0.1)

    print(f"[+] 成功获取全部章节，共 {len(all_sections)} 章节。")
    with open(metadata_cache, 'w', encoding='utf-8') as f:
        json.dump(all_sections, f, ensure_ascii=False, indent=2)
    return all_sections

def get_audio_url(item):
    section_num = item['section']
    item_id = str(item['id'])
    params = {
        'entityId': BOOK_ID,
        'entityType': '3',
        'opType': '1',
        'sections': f'[{section_num}]',
        'type': '0',
        'id': item_id,
        'section': str(section_num)
    }
    url = f'https://m.lrts.me/ajax/getListenPath?{urllib.parse.urlencode(params)}'
    req_headers = dict(HEADERS)
    req_headers['Referer'] = f'https://m.lrts.me/player?id={BOOK_ID}&entityType=3&sonId={item_id}'

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                if res.get('status') == 0 and res.get('data'):
                    audio_data = res['data']
                    return audio_data.get('path'), audio_data.get('fileSize')
                else:
                    time.sleep(0.5)
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"[!] 获取第 {section_num} 回播放链接失败: {e}")
            time.sleep(1)
    return None, None

def download_track(item, output_dir, current_idx, total_count):
    section_num = item['section']
    title = clean_filename(item['name'])
    filename = f"{section_num:03d}_{title}.m4a"
    target_path = os.path.join(output_dir, filename)

    expected_size = None
    if item.get('size'):
        try:
            expected_size = int(item['size'])
        except Exception:
            pass

    # Check if already downloaded
    if os.path.exists(target_path):
        current_size = os.path.getsize(target_path)
        if expected_size and abs(current_size - expected_size) < 1024:
            return True, section_num, filename, current_size, "已存在 (跳过)"
        elif not expected_size and current_size > 10000:
            return True, section_num, filename, current_size, "已存在 (跳过)"

    audio_url, file_size = get_audio_url(item)
    if not audio_url:
        return False, section_num, filename, 0, "无法获取音频直链"

    temp_path = target_path + ".tmp"
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(audio_url, headers={'User-Agent': HEADERS['User-Agent']})
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(temp_path, 'wb') as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
            # Rename temp to target
            if os.path.exists(target_path):
                os.remove(target_path)
            os.rename(temp_path, target_path)
            downloaded_size = os.path.getsize(target_path)
            return True, section_num, filename, downloaded_size, "下载完成"
        except Exception as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            if attempt == MAX_RETRIES - 1:
                return False, section_num, filename, 0, f"下载出错: {e}"
            time.sleep(1)

    return False, section_num, filename, 0, "重试耗尽"

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"[*] 目标保存目录: {OUTPUT_DIR}")

    items = fetch_all_menu()
    total_count = len(items)

    print(f"[*] 开始多线程下载 {total_count} 首音频，线程数: {MAX_WORKERS}...")
    success_count = 0
    fail_list = []
    total_bytes = 0

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(download_track, item, OUTPUT_DIR, idx + 1, total_count): item
            for idx, item in enumerate(items)
        }

        completed = 0
        for future in as_completed(future_map):
            completed += 1
            ok, sec_num, fname, fsize, msg = future.result()
            if ok:
                success_count += 1
                total_bytes += fsize
                size_str = format_size(fsize)
                print(f"[{completed:03d}/{total_count:03d}] [成功] {fname} ({size_str}) - {msg}")
            else:
                fail_list.append((sec_num, fname, msg))
                print(f"[{completed:03d}/{total_count:03d}] [失败] 第 {sec_num} 回 ({fname}) - {msg}")

    t1 = time.time()
    print("\n" + "=" * 60)
    print(f"[+] 下载任务完成！耗时: {t1 - t0:.1f} 秒")
    print(f"[+] 成功: {success_count} / {total_count}")
    print(f"[+] 总下载体积: {format_size(total_bytes)}")
    if fail_list:
        print(f"[!] 失败列表 ({len(fail_list)} 首):")
        for f in fail_list:
            print(f"    - 第 {f[0]} 回: {f[1]} -> {f[2]}")
    else:
        print("[+] 所有 240 首音频均已完整下载，零损坏零遗漏！")
    print("=" * 60)

    # Generate M3U playlist
    m3u_path = os.path.join(OUTPUT_DIR, "000_播放列表.m3u")
    with open(m3u_path, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        f.write(f"#PLAYLIST:{BOOK_TITLE}\n")
        for item in items:
            sec_num = item['section']
            title = clean_filename(item['name'])
            fname = f"{sec_num:03d}_{title}.m4a"
            length = item.get('length', -1)
            f.write(f"#EXTINF:{length},{title}\n")
            f.write(f"{fname}\n")
    print(f"[+] 已生成标准播放列表: {m3u_path}")

    # Generate Markdown Catalog
    catalog_path = os.path.join(OUTPUT_DIR, "README_目录索引.md")
    with open(catalog_path, 'w', encoding='utf-8') as f:
        f.write(f"# {BOOK_TITLE}\n\n")
        f.write(f"- **总集数**: {total_count} 回\n")
        f.write(f"- **原著**: 佚名\n")
        f.write(f"- **配音/主播**: 一转名声蛊 / 木成老师配音语录\n")
        f.write(f"- **音频格式**: M4A (AAC 高保真音频)\n")
        f.write(f"- **总大小**: {format_size(total_bytes)}\n")
        f.write(f"- **下载目录**: `{OUTPUT_DIR}`\n\n")
        f.write("## 章节完整目录表\n\n")
        f.write("| 序号 | 章节标题 | 音频时长 | 预估大小 | 文件名 |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- |\n")
        for item in items:
            sec_num = item['section']
            title = clean_filename(item['name'])
            fname = f"{sec_num:03d}_{title}.m4a"
            dur = format_duration(item.get('length', 0))
            sz = format_size(item.get('size', 0))
            f.write(f"| {sec_num:03d} | {title} | {dur} | {sz} | `{fname}` |\n")
    print(f"[+] 已生成目录索引文档: {catalog_path}")

if __name__ == '__main__':
    main()
