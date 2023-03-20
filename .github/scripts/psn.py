import os
from base64 import b64encode
from datetime import datetime
from nacl import encoding, public
import requests


npsso = os.environ.get('NPSSO')  # https://ca.account.sony.com/api/v1/ssocookie
psn_access_token = os.environ.get('PSN_ACCESS_TOKEN')
psn_refresh_token = os.environ.get('PSN_REFRESH_TOKEN')
github_token = os.environ.get('CI_TOKEN')

psn_user = 'swilder-ming'
auth_base_url = 'https://ca.account.sony.com/api/authz/v3/'

def get_psn_code():
    params = {
      'access_type': 'offline',
      'client_id': '09515159-7237-4370-9b40-3806e67c0891',
      'redirect_uri': 'com.scee.psxandroid.scecompcall://redirect',
      'response_type': 'code',
      'scope': 'psn:mobile.v2.core psn:clientapp',
    }
    cookies = {'npsso': npsso}
    resp = requests.get(auth_base_url + 'oauth/authorize', params=params, cookies=cookies, allow_redirects=False)
    if resp.status_code != 302:
        return None
    return resp.headers['Location'].split('code=')[1].split('&')[0]


def get_psn_token():
    code = get_psn_code()
    if not code:
        raise Exception('Failed to get code')
    data = {
      'code': code,
      'grant_type': 'authorization_code',
      'redirect_uri': 'com.scee.psxandroid.scecompcall://redirect',
      'token_format': 'jwt'
    }
    headers = {
      'Authorization': 'Basic MDk1MTUxNTktNzIzNy00MzcwLTliNDAtMzgwNmU2N2MwODkxOnVjUGprYTV0bnRCMktxc1A=',
      'Content-Type': 'application/x-www-form-urlencoded',
    }
    resp = requests.post(auth_base_url + 'oauth/token', data=data, headers=headers)
    if resp.status_code != 200:
        print(resp.status_code)
        print(resp.text)
        raise Exception('Failed to get token')
    record = resp.json()
    return record['access_token'], record['refresh_token']


def refresh_psn_token():
    data = {
      'refresh_token': psn_refresh_token,
      'grant_type': 'refresh_token',
      'scope': 'psn:mobile.v2.core psn:clientapp',
      'token_format': 'jwt'
    }
    headers = {
      'Authorization': 'Basic MDk1MTUxNTktNzIzNy00MzcwLTliNDAtMzgwNmU2N2MwODkxOnVjUGprYTV0bnRCMktxc1A=',
      'Content-Type': 'application/x-www-form-urlencoded',
    }
    resp = requests.post(auth_base_url + 'oauth/token', data=data, headers=headers)
    if resp.status_code != 200:
        return None, None
    record = resp.json()
    return record['access_token'], record['refresh_token']


def check_psn_token():
    if not psn_access_token:
        return False
    url = f'https://us-prof.np.community.playstation.net/userProfile/v1/users/{psn_user}/profile2?fields=npId,onlineId,accountId,avatarUrls,plus'
    headers = {
        'Authorization': f'Bearer {psn_access_token}',
        'Content-Type': 'application/json',
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return False
    return True


def convert_play_duration(duration_str):
    # PT0S -> 0 mins
    # PT3M8S -> 3 mins
    # PT9H3S -> 9 hrs
    # PT20H30S -> 20 hrs 30 mins
    # PT184H1M8S -> 184 hrs 1 min

    if not duration_str:
        return '0 mins'
    duration_str = duration_str.replace('PT', '')
    duration_str = duration_str.replace('S', ' secs')
    duration_str = duration_str.replace('M', ' mins ')
    duration_str = duration_str.replace('H', ' hrs ')
    if 'mins' not in duration_str:
        if 'hrs' not in duration_str:
            return '0 mins'
        duration_str = duration_str.split('hrs')[0] + 'hrs'
    else:
        duration_str = duration_str.split('mins')[0] + 'mins'
    return duration_str.strip()


def set_img_html(img_url):
    # <img src="xxx" style="zoom:5%;" />
    return f'<img src="{img_url}" style="max-width:60%;" />'


def draw_progress_bar(percent, bar_length=10):
    filled_length = int(bar_length * percent / 100)  # 已经填充的长度
    remaining_length = bar_length - filled_length  # 剩余长度

    # 根据已填充和剩余的长度，构造进度条的字符画
    bar = '█' * filled_length + '░' * remaining_length

    # 根据已填充的长度，确定进度条末尾的字符
    if filled_length == 0:
        end_char = '░'
    elif filled_length == bar_length:
        end_char = '█'
    else:
        end_char_index = int((filled_length % 1) * 8)
        end_char = '▏▎▍▌▋▊▉█'[end_char_index]

    # 在进度条末尾添加结束字符
    bar += end_char

    return bar


def get_trophy_list(offset=0, limit=800):
    url = 'https://m.np.playstation.com/api/trophy/v1/users/me/trophyTitles'
    headers = {
        'Authorization': f'Bearer {psn_access_token}',
        'Content-Type': 'application/json'
    }
    params = {
        'limit': limit,
        'offset': offset,
        'accountId': 'me'
    }
    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        return None
    resp = resp.json()
    trophy_titles = resp['trophyTitles']
    next_offset = resp.get('nextOffset')
    if next_offset:
        trophy_titles += get_trophy_list(next_offset)
    return trophy_titles


def get_specific_title_trophy_list(title_id):
    url = 'https://m.np.playstation.com/api/trophy/v1/users/me/titles/trophyTitles'
    headers = {
        'Authorization': f'Bearer {psn_access_token}',
        'Content-Type': 'application/json'
    }
    params = {
        'accountId': 'me',
        'npTitleIds': title_id
    }
    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        return None

    resp = resp.json()
    for title in resp['titles']:
        if title['npTitleId'] == title_id and title['trophyTitles']:
            return title['trophyTitles'][0]
    return None


def get_game_list(offset=0, limit=250):
    url = f'https://m.np.playstation.com/api/gamelist/v2/users/me/titles?limit={limit}&offset={offset}'
    headers = {
        'Authorization': f'Bearer {psn_access_token}',
        'Content-Type': 'application/json',
        # 'Accept-Language': 'zh-CN'  # game name & image
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return None

    resp = resp.json()
    titles = resp['titles']
    next_offset = resp.get('nextOffset')
    if next_offset:
        titles += get_game_list(offset=next_offset)
    return titles


def sort_trophy_titles(trophys):
    trophys.sort(key=lambda _t: _t['progress'], reverse=True)
    records = [
        {
            'title': _t['trophyTitleName'],
            'trophyTitleIconUrl': _t['trophyTitleIconUrl'],
            'trophyTitlePlatform': _t['trophyTitlePlatform'],
            'definedTrophies': _t['definedTrophies'],
            'earnedTrophies': _t['earnedTrophies'],
            'definedTrophiesTotal': sum(_t['definedTrophies'].values()),
            'earnedTrophiesTotal': sum(_t['earnedTrophies'].values()),
            'npCommunicationId': _t['npCommunicationId']
        }
        for _t in trophys if _t['progress'] > 0
    ]
    return records


def output_games(game_list):
    print('---')
    print('title: "Playstation Games"')
    print(f'date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")}')
    print('draft: false')
    print('---')
    print()

    print('| Game | Duration | Trophies | Progress |')
    print('|:--------:|:--------:|:--------:|:--------:|')
    for _g in game_list:
        # | <img src="xxx" style="zoom:5%;" />  Ghost of Tsushima | 80 hrs 55 mins  | 1 / 2 / 10 / 45 | ███████░░░▏ |
        print('|', set_img_html(_g['image']), '|', _g['playDuration'], '|', end=' ')
        trophies = [_g['earnedTrophies'][_k] for _k in ['platinum', 'gold', 'silver', 'bronze']]
        # print(' / '.join([str(_t) for _t in trophies]), '|', f"{_g['progress']:.2f}%", '|')
        print(' / '.join([str(_t) for _t in trophies]), '|', draw_progress_bar(_g['progress']), '|')


def update_github_repo_secret(secret_records):
    request_headers = {
        'Accept': 'application/vnd.github.v3+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Authorization': f'Bearer {github_token}'
    }
    public_key_info = requests.get(
        url='https://api.github.com/repos/Swilder-M/blog/actions/secrets/public-key',
        headers=request_headers
    ).json()
    public_key = public.PublicKey(public_key_info['key'].encode('utf-8'), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)

    url = f'https://api.github.com/repos/Swilder-M/blog/actions/secrets/'
    for _k in ['PSN_ACCESS_TOKEN', 'PSN_REFRESH_TOKEN']:
        encrypted = sealed_box.encrypt(secret_records[_k].encode('utf-8'))
        data = {
            'encrypted_value': b64encode(encrypted).decode('utf-8'),
            'key_id': public_key_info['key_id']
        }
        requests.put(url + _k, headers=request_headers, json=data)


if __name__ == '__main__':
    if not check_psn_token():
        psn_access_token, psn_refresh_token = refresh_psn_token()
        if not psn_access_token:
            psn_access_token, psn_refresh_token = get_psn_token()
        update_github_repo_secret({
            'PSN_ACCESS_TOKEN': psn_access_token,
            'PSN_REFRESH_TOKEN': psn_refresh_token
        })

    all_games = get_game_list()
    valid_records = []
    for _g in all_games:
        play_duration = convert_play_duration(_g.get('playDuration'))
        if play_duration == '0 mins':
            continue

        _trophys = get_specific_title_trophy_list(_g['titleId'])
        if not _trophys:
            continue

        _record = {
            'name': _g['name'],
            'image': _g['imageUrl'],
            'platform': _g['category'].split('_')[0],
            'playDuration': play_duration,
            'definedTrophies': _trophys['definedTrophies'],
            'earnedTrophies': _trophys['earnedTrophies'],
            'definedTrophiesTotal': sum(_trophys['definedTrophies'].values()),
            'earnedTrophiesTotal': sum(_trophys['earnedTrophies'].values()),
            'titleId': _g['titleId']
        }
        _record['progress'] = round(_record['earnedTrophiesTotal'] / _record['definedTrophiesTotal'] * 100, 2)
        
        if 'hrs' not in play_duration and _record['progress'] < 1.00:
            continue

        valid_records.append(_record)

    valid_records.sort(key=lambda _t: _t['progress'], reverse=True)
    output_games(valid_records)
