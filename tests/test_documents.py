"""Private document flow: upload intent, signed upload, confirmation checks, authorised and
audited short-lived downloads."""
import hashlib
import json

from sqlalchemy import text

from app.storage import set_scanner, sign
from helpers import assign_patient, audit_events, make_patient

PDF = b"%PDF-1.7\n" + b"Discharge summary for the patient.\n" * 20 + b"%%EOF"


def start_upload(client, headers, patient_id, content=PDF, **body):
    response = client.post(f"/api/v1/patients/{patient_id}/documents", headers=headers, json={
        "original_filename": "discharge.pdf", "mime_type": "application/pdf", "size_bytes": len(content),
        "category": "LETTER", **body})
    return response


def upload(client, headers, patient_id, content=PDF, content_type="application/pdf", **body):
    intent = start_upload(client, headers, patient_id, content, **body)
    assert intent.status_code == 201, intent.text
    put = client.put(intent.json()["upload_url"], content=content, headers={"Content-Type": content_type})
    assert put.status_code == 204, put.text
    return intent.json()["document"]["id"]


def upload_and_confirm(client, headers, patient_id, **body):
    document_id = upload(client, headers, patient_id, **body)
    confirmed = client.post(f"/api/v1/documents/{document_id}/confirm", headers=headers,
                            json={"checksum_sha256": hashlib.sha256(PDF).hexdigest()})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def test_upload_and_download_flow(client, org_a, test_engine, private_storage):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    document = upload_and_confirm(client, ops, patient["id"], title="Hospital discharge")
    assert document["status"] == "AVAILABLE" and document["checksum_sha256"] == hashlib.sha256(PDF).hexdigest()

    # Stored under a random key, not the file name.
    with test_engine.connect() as db:
        key = db.execute(text("SELECT storage_key FROM documents WHERE id = :id"),
                         {"id": document["id"]}).scalar_one()
    assert "discharge" not in key and private_storage.exists(key)

    link = client.post(f"/api/v1/documents/{document['id']}/download-link", headers=ops).json()
    assert link["download_url"].startswith("/api/v1/storage/download/")
    downloaded = client.get(link["download_url"])
    assert downloaded.status_code == 200 and downloaded.content == PDF
    assert downloaded.headers["content-type"] == "application/pdf"
    assert "attachment" in downloaded.headers["content-disposition"]

    actions = [e["action"] for e in audit_events(test_engine) if e["resource_type"] == "document"]
    assert {"document.upload_intent", "document.upload", "document.download_link", "document.download"} <= set(actions)
    # The audit log never holds the file content or the signed link.
    everything = json.dumps(audit_events(test_engine), default=str)
    assert "Discharge summary" not in everything and link["download_url"].split("/")[-1] not in everything


def test_download_requires_current_authorisation(client, org_a, test_engine):
    """Mandatory scenario: knowing the id/storage key (or holding an old link) is not enough."""
    ops, care = org_a["ops"]["headers"], org_a["care"]["headers"]
    patient = make_patient(client, org_a)
    assign_patient(client, org_a, patient["id"])
    document = upload_and_confirm(client, ops, patient["id"])
    with test_engine.connect() as db:
        key = db.execute(text("SELECT storage_key FROM documents WHERE id = :id"),
                         {"id": document["id"]}).scalar_one()

    # The storage key or the document id is not a way in.
    assert client.get(f"/api/v1/storage/download/{key}").status_code in (403, 404)
    assert client.get(f"/api/v1/storage/download/{document['id']}").status_code == 403
    assert client.get(f"/api/v1/documents/{document['id']}", headers=org_a["coord"]["headers"]).status_code == 403

    # Care staff get a link while assigned...
    link = client.post(f"/api/v1/documents/{document['id']}/download-link", headers=care).json()["download_url"]
    assignment = client.get(f"/api/v1/patients/{patient['id']}/assignments", headers=ops).json()[0]
    client.post(f"/api/v1/patients/{patient['id']}/assignments/{assignment['id']}/end", headers=ops)
    # ...but once they are no longer assigned, the still-unexpired link stops working.
    assert client.get(link).status_code == 404

    ops_link = client.post(f"/api/v1/documents/{document['id']}/download-link", headers=ops).json()["download_url"]
    client.post(f"/api/v1/users/{org_a['ops']['id']}/deactivate", headers=org_a["sysadmin"]["headers"])
    assert client.get(ops_link).status_code == 403


def test_signed_links_cannot_be_forged_reused_or_kept(client, org_a):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    document = upload_and_confirm(client, ops, patient["id"])
    url = client.post(f"/api/v1/documents/{document['id']}/download-link", headers=ops).json()["download_url"]
    token = url.split("/")[-1]

    body, signature = token.split(".")
    assert client.get(f"/api/v1/storage/download/{body}.{signature[:-2]}xx").status_code == 403
    assert client.get(f"/api/v1/storage/download/{body}").status_code == 403
    # An upload token is not a download token, and expired tokens are refused.
    upload_token, _ = sign("upload", document["id"], org_a["ops"]["id"], "crm")
    assert client.get(f"/api/v1/storage/download/{upload_token}").status_code == 403
    expired, _ = sign("download", document["id"], org_a["ops"]["id"], "crm", seconds=-5)
    assert client.get(f"/api/v1/storage/download/{expired}").status_code == 403

    client.post(f"/api/v1/documents/{document['id']}/archive", headers=ops, json={"reason": "Duplicate"})
    assert client.get(url).status_code == 409
    assert client.post(f"/api/v1/documents/{document['id']}/download-link", headers=ops).status_code == 409


def test_upload_checks(client, org_a, private_storage):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)

    assert start_upload(client, ops, patient["id"], mime_type="application/x-msdownload",
                        original_filename="setup.exe").status_code == 422
    assert start_upload(client, ops, patient["id"], original_filename="photo.png").status_code == 422
    assert start_upload(client, ops, patient["id"], size_bytes=50 * 1024 * 1024).status_code == 422
    assert start_upload(client, ops, patient["id"], original_filename="../../etc/passwd.pdf").status_code == 422

    # An executable renamed to .pdf is rejected after upload and the file is deleted.
    fake = b"MZ\x90\x00" + b"\x00" * 200
    fake_id = upload(client, ops, patient["id"], content=fake)
    rejected = client.post(f"/api/v1/documents/{fake_id}/confirm", headers=ops, json={})
    assert rejected.status_code == 422 and "CONTENT_TYPE_MISMATCH" in rejected.json()["error"]["message"]
    listed = client.get(f"/api/v1/patients/{patient['id']}/documents?status=REJECTED", headers=ops).json()["data"]
    assert [d["rejected_reason"] for d in listed] == ["CONTENT_TYPE_MISMATCH"]
    assert not any(private_storage.root.rglob("*")) or all(p.is_dir() for p in private_storage.root.rglob("*"))

    intent = start_upload(client, ops, patient["id"]).json()
    url = intent["upload_url"]
    assert client.put(url, content=PDF, headers={"Content-Type": "image/png"}).status_code == 415
    assert client.put(url, content=PDF + b"extra", headers={"Content-Type": "application/pdf"}).status_code == 413
    assert client.put(url, content=PDF, headers={"Content-Type": "application/pdf"}).status_code == 204
    assert client.put(url, content=PDF, headers={"Content-Type": "application/pdf"}).status_code == 409
    wrong_sum = client.post(f"/api/v1/documents/{intent['document']['id']}/confirm", headers=ops,
                            json={"checksum_sha256": "0" * 64})
    assert wrong_sum.status_code == 422


def test_malware_hook_rejects_infected_files(client, org_a):
    class InfectedScanner:
        def scan(self, storage, key):
            return "INFECTED"

    set_scanner(InfectedScanner())
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    document_id = upload(client, ops, patient["id"])
    response = client.post(f"/api/v1/documents/{document_id}/confirm", headers=ops, json={})
    assert response.status_code == 422 and "MALWARE_DETECTED" in response.json()["error"]["message"]


def test_clinical_documents_follow_note_visibility(client, org_a, org_b):
    care, ops = org_a["care"]["headers"], org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    assign_patient(client, org_a, patient["id"])
    # Ops admins have no clinical access: they can neither upload nor see CLINICAL documents.
    assert start_upload(client, ops, patient["id"], visibility="CLINICAL").status_code == 403
    clinical = upload_and_confirm(client, care, patient["id"], visibility="CLINICAL", category="ASSESSMENT")
    assert client.get(f"/api/v1/documents/{clinical['id']}", headers=ops).status_code == 404
    assert client.get(f"/api/v1/patients/{patient['id']}/documents", headers=ops).json()["data"] == []
    assert len(client.get(f"/api/v1/patients/{patient['id']}/documents", headers=care).json()["data"]) == 1
    assert client.get(f"/api/v1/documents/{clinical['id']}", headers=org_b["ops"]["headers"]).status_code == 404
