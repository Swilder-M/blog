import os, json
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


def get_trophy_titles(offset=0, limit=800):
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
        trophy_titles += get_trophy_titles(next_offset)
    return trophy_titles


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
        }
        for _t in trophys if _t['progress'] > 0
    ]
    return records


def output_trophy_titles(trophys):
    print('---')
    print('title: "Playstation Games"')
    print(f'date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")}')
    print('draft: false')
    print('---')
    print()
    print('| Name | Platform | Platinum | Gold | Silver | Bronze | Progress |')
    print('|:---- |:--------:|:--------:|:----:|:------:|:------:|:--------:|')
    for _t in trophys:
        # | Ghost of Tsushima | PS5 | `1/1` | `2/4` | `10/13` | `45/59` | `58/77` |
        print('|', _t['title'].strip(), '|', _t['trophyTitlePlatform'], '|', end=' ')
        for _k in ['platinum', 'gold', 'silver', 'bronze']:
            print(f"`{_t['earnedTrophies'][_k]}/{_t['definedTrophies'][_k]}`", end=' | ')
        print(f"`{_t['earnedTrophiesTotal']}/{_t['definedTrophiesTotal']}`", end=' |')
        print()


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
    trophys = sort_trophy_titles(get_trophy_titles())
    output_trophy_titles(trophys)
