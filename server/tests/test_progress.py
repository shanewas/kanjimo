import json
import threading

from fastapi.testclient import TestClient

from conftest import CSRF, IP
from helpers import login, other_client

STORE = {"version": 4, "level": 1, "items": {}, "days": {}, "settings": {}, "session": None}


def put(client, store, rev):
    return client.put("/api/progress", json={"store": store}, headers={"If-Match": f'"{rev}"'})


def test_roundtrip(client):
    login(client)
    assert client.get("/api/progress").status_code == 204
    r = put(client, STORE, 0)
    assert r.status_code == 200 and r.json()["rev"] == 1
    r = client.get("/api/progress")
    assert r.status_code == 200 and r.json()["rev"] == 1 and r.json()["store"] == STORE
    assert put(client, {**STORE, "level": 2}, 1).json()["rev"] == 2
    assert put(client, {**STORE, "version": 3}, "2").status_code == 200


def test_n14_users_are_isolated(client):
    login(client, "a@example.com")
    assert put(client, STORE, 0).status_code == 200
    b = other_client(client)
    login(b, "b@example.com")
    assert b.get("/api/progress").status_code == 204
    r = put(b, STORE, 1)
    assert r.status_code == 409 and r.json() == {"rev": 0, "store": None}
    assert b.put("/api/progress", json={"store": STORE}).status_code == 428
    r = client.get("/api/progress")
    assert r.json()["rev"] == 1 and r.json()["store"] == STORE


def test_n33_size_cap(client):
    login(client)
    base = {"version": 4, "items": {}, "days": {}, "pad": ""}
    size = len(json.dumps(base, separators=(",", ":")).encode())
    big = {**base, "pad": "x" * (1_048_577 - size)}
    assert len(json.dumps(big, separators=(",", ":")).encode()) == 1_048_577
    r = put(client, big, 0)
    assert r.status_code == 413 and r.json() == {"error": "too_large"}
    big["pad"] = big["pad"][:-1]
    assert put(client, big, 0).status_code == 200


def test_n34_bad_shapes(client):
    login(client)
    assert put(client, [], 0).status_code == 400
    assert put(client, {"version": 9, "items": {}, "days": {}}, 0).status_code == 400
    assert put(client, {"version": 4, "items": {str(i): {} for i in range(20_001)}, "days": {}}, 0).status_code == 400
    assert put(client, {"version": 4, "items": {}, "days": {str(i): {} for i in range(4_001)}}, 0).status_code == 400
    assert put(client, {"version": 4, "items": {"k" * 65: {}}, "days": {}}, 0).status_code == 400
    assert put(client, {"version": 4, "items": [], "days": {}}, 0).status_code == 400
    assert client.put("/api/progress", json={}, headers={"If-Match": '"0"'}).status_code == 400
    assert client.put("/api/progress", json=[1], headers={"If-Match": '"0"'}).status_code == 400
    assert client.get("/api/progress").status_code == 204


def test_n35_if_match(client):
    login(client)
    assert client.put("/api/progress", json={"store": STORE}).status_code == 428
    assert client.put("/api/progress", json={"store": STORE}, headers={"If-Match": "abc"}).status_code == 428
    assert put(client, STORE, 0).status_code == 200
    assert put(client, {**STORE, "level": 2}, 1).status_code == 200
    r = put(client, {**STORE, "level": 3}, 1)
    assert r.status_code == 409 and r.json()["rev"] == 2 and r.json()["store"]["level"] == 2
    assert put(client, STORE, 0).status_code == 409


def test_n36_concurrent_puts_with_the_same_revision(client):
    login(client)
    assert put(client, STORE, 0).status_code == 200
    cookies = {"__Host-jstudy": client.cookies.get("__Host-jstudy")}
    barrier = threading.Barrier(2)
    results = []

    def push(level):
        c = TestClient(client.app, base_url="https://testserver", client=IP, headers=CSRF, cookies=cookies)
        barrier.wait()
        results.append(put(c, {**STORE, "level": level}, 1).status_code)

    threads = [threading.Thread(target=push, args=(n,)) for n in (2, 3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409]
    assert client.get("/api/progress").json()["rev"] == 2
