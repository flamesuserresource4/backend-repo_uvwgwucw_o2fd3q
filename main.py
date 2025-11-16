import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document
from schemas import Component, Build, Comment

app = FastAPI(title="RigArchitect API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Utility to convert ObjectId to string
class Obj(BaseModel):
    id: str


def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


@app.get("/")
def root():
    return {"service": "RigArchitect API"}


# ============ Components ============
@app.post("/api/components", response_model=Dict[str, str])
def add_component(component: Component):
    inserted_id = create_document("component", component)
    return {"id": inserted_id}


@app.get("/api/components")
def list_components(type: Optional[str] = None, q: Optional[str] = None, limit: int = 200):
    filt: Dict[str, Any] = {}
    if type:
        filt["type"] = type
    if q:
        filt["name"] = {"$regex": q, "$options": "i"}
    items = list(db["component"].find(filt).limit(limit))
    for it in items:
        it["id"] = str(it.pop("_id"))
    return items


class BulkImport(BaseModel):
    items: List[Component]


@app.post("/api/components/import")
def import_components(payload: BulkImport):
    count = 0
    for comp in payload.items:
        create_document("component", comp)
        count += 1
    return {"imported": count}


# ============ Builds ============
@app.post("/api/builds")
def create_build(build: Build):
    # compute total price
    total = 0.0
    for bc in build.components:
        doc = db["component"].find_one({"_id": oid(bc.component_id)})
        if not doc:
            raise HTTPException(status_code=404, detail=f"Component not found: {bc.component_id}")
        if doc.get("price"):
            total += float(doc["price"])
    bdict = build.model_dump()
    bdict["total_price"] = total

    # compatibility checks
    problems = compatibility_issues(build)
    if problems:
        raise HTTPException(status_code=400, detail={"errors": problems})

    inserted_id = db["build"].insert_one(bdict).inserted_id
    return {"id": str(inserted_id), "total_price": total}


@app.get("/api/builds")
def list_builds(top_loved: bool = False, limit: int = 50):
    cursor = db["build"].find({}).sort("likes", -1 if top_loved else 1).limit(3 if top_loved else limit)
    items = list(cursor)
    for it in items:
        it["id"] = str(it.pop("_id"))
    return items


@app.get("/api/builds/{build_id}")
def get_build(build_id: str):
    doc = db["build"].find_one({"_id": oid(build_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Build not found")
    doc["id"] = str(doc.pop("_id"))
    # expand components
    expanded = []
    for bc in doc.get("components", []):
        c = db["component"].find_one({"_id": oid(bc["component_id"])})
        if c:
            c["id"] = str(c.pop("_id"))
            expanded.append({**bc, "component": c})
    doc["components_expanded"] = expanded
    # comments
    comments = list(db["comment"].find({"build_id": build_id}).sort("created_at", -1))
    for cm in comments:
        cm["id"] = str(cm.pop("_id"))
    doc["comments"] = comments
    return doc


@app.patch("/api/builds/{build_id}")
def update_build(build_id: str, is_anchor: Optional[bool] = None, title: Optional[str] = None, description: Optional[str] = None):
    update: Dict[str, Any] = {}
    if is_anchor is not None:
        update["is_anchor"] = is_anchor
    if title is not None:
        update["title"] = title
    if description is not None:
        update["description"] = description
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = db["build"].update_one({"_id": oid(build_id)}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Build not found")
    return {"updated": True}


# Validation endpoint
@app.post("/api/builds/validate")
def validate_build(build: Build):
    issues = compatibility_issues(build)
    watts = estimate_wattage(build)
    return {"issues": issues, "estimated_wattage": watts}


# ============ Likes & Comments ============
@app.post("/api/builds/{build_id}/like")
def like_build(build_id: str, user_id: str):
    existing = db["like"].find_one({"build_id": build_id, "user_id": user_id})
    if existing:
        raise HTTPException(status_code=400, detail="Already liked")
    db["like"].insert_one({"build_id": build_id, "user_id": user_id})
    db["build"].update_one({"_id": oid(build_id)}, {"$inc": {"likes": 1}})
    return {"status": "ok"}


@app.post("/api/builds/{build_id}/comment")
def comment_build(build_id: str, payload: Comment):
    if payload.build_id != build_id:
        raise HTTPException(status_code=400, detail="build_id mismatch")
    cid = create_document("comment", payload)
    return {"id": cid}


# ============ Admin ============
@app.get("/api/admin/anchor-builds")
def list_anchor_builds():
    items = list(db["build"].find({"is_anchor": True}).sort("likes", -1))
    for it in items:
        it["id"] = str(it.pop("_id"))
    return items


# ============ Compatibility ============

def compatibility_issues(build: Build) -> List[str]:
    comps = {bc.type: db["component"].find_one({"_id": oid(bc.component_id)}) for bc in build.components}
    issues: List[str] = []

    cpu = comps.get("cpu")
    mobo = comps.get("motherboard")
    ram = comps.get("ram")
    gpu = comps.get("gpu")
    case = comps.get("case")
    psu = comps.get("psu")
    cooler = comps.get("cooler")

    # Socket match
    if cpu and mobo and cpu.get("socket") and mobo.get("socket"):
        if cpu["socket"].lower() != mobo["socket"].lower():
            issues.append(f"CPU socket {cpu['socket']} not compatible with motherboard {mobo['socket']}")

    # RAM type
    if ram and mobo and ram.get("ram_type") and mobo.get("ram_type"):
        if ram["ram_type"].lower() != mobo["ram_type"].lower():
            issues.append(f"RAM type {ram['ram_type']} not compatible with motherboard {mobo['ram_type']}")

    # GPU length vs case
    if gpu and case and gpu.get("gpu_length_mm") and case.get("max_gpu_length_mm"):
        if int(gpu["gpu_length_mm"]) > int(case["max_gpu_length_mm"]):
            issues.append("GPU length exceeds case maximum")

    # Cooler height vs case
    if cooler and case and cooler.get("cooler_height_mm") and case.get("case_max_cooler_height_mm"):
        if int(cooler["cooler_height_mm"]) > int(case["case_max_cooler_height_mm"]):
            issues.append("Cooler height exceeds case maximum")

    # PSU wattage
    est_watts = estimate_wattage(build)
    if psu and psu.get("psu_wattage") and est_watts:
        if int(psu["psu_wattage"]) < est_watts:
            issues.append(f"PSU wattage too low. Estimated {est_watts}W, PSU is {psu['psu_wattage']}W")

    # PSU form factor vs case
    if psu and case and psu.get("psu_form_factor") and case.get("case_supported_psu"):
        if psu["psu_form_factor"] not in case["case_supported_psu"]:
            issues.append("PSU form factor not supported by case")

    # Motherboard form factor vs case support
    if mobo and case and mobo.get("motherboard_form_factor") and case.get("case_motherboard_support"):
        if mobo["motherboard_form_factor"] not in case["case_motherboard_support"]:
            issues.append("Motherboard form factor not supported by case")

    return issues


def estimate_wattage(build: Build) -> int:
    total_tdp = 0
    for bc in build.components:
        comp = db["component"].find_one({"_id": oid(bc.component_id)})
        if comp and comp.get("tdp"):
            total_tdp += int(comp["tdp"])
    return int(total_tdp * 1.3) if total_tdp else 0


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            collections = db.list_collection_names()
            response["collections"] = collections[:10]
            response["database"] = "✅ Connected & Working"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
