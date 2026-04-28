# Test fixtures

## FanGraphs leaderboard JSON

`fg_leaderboard_bat_2024.json` and `fg_leaderboard_pit_2024.json` are real,
trimmed responses from fangraphs.com's public JSON API. They stand in for a
VCR cassette — `vcrpy` can't intercept `curl_cffi` (which speaks libcurl
natively), so we record-and-replay by hand.

Tests load these fixtures via `_FakeResp` in `test_statcast.py`.

### Refreshing a fixture

If FanGraphs changes columns and the tests start failing, re-record:

```bash
uv run python -c "
from curl_cffi import requests as cc
import json

for kind in ('bat', 'pit'):
    params = {
        'age': '', 'pos': 'all', 'stats': kind, 'lg': 'all', 'qual': 50,
        'season': 2024, 'season1': 2024, 'ind': 0, 'team': 0, 'month': 0,
        'pageitems': 10,
    }
    r = cc.get('https://www.fangraphs.com/api/leaders/major-league/data',
               params=params, impersonate='chrome', timeout=20)
    r.raise_for_status()
    data = r.json()
    data['data'] = data.get('data', [])[:5]  # trim to keep commit small
    with open(f'tests/fixtures/fg_leaderboard_{kind}_2024.json', 'w') as f:
        json.dump(data, f, indent=2)
"
```

If the column assertions in `TestFetchFgLeaderboardRecorded` also need to
change, update them — the new FG shape is the new contract.
