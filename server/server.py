from fastapi import FastAPI
from pydantic import BaseModel
import requests
import time
import threading

simbrief_flightplan = {}
simbrief_id = 123456

vatsim_data = {}
vatsim_cid = 1234567

def main():
    global simbrief_flightplan, vatsim_data
    while True:
        if simbrief_id:
            simbrief_flightplan = requests.get("https://www.simbrief.com/api/xml.fetcher.php?userid={0}&json=1".format(simbrief_id)).json()
            simbrief_flightplan = dict((key, simbrief_flightplan[key]) for key in ["general","origin","destination","navlog","aircraft","tlr"])
        if vatsim_cid:
            vatsim_data = [data for data in requests.get("https://data.vatsim.net/v3/vatsim-data.json").json()["pilots"] if data["cid"] == int(vatsim_cid)]
        time.sleep(3)

app = FastAPI()

@app.on_event("startup")
def startup_event():
    threading.Thread(target=main).start() 

class Config(BaseModel):
    simbrief_id: int
    vatsim_cid: int

@app.get("/")
def read_root(config: Config):
    simbrief_id = config.simbrief_id
    vatsim_cid = config.vatsim_cid
    return {"status":"Success"}

@app.get("/simbrief")
def read_simbrief():
    global simbrief_flightplan
    return {"simbrief":simbrief_flightplan}

@app.get("/vatsim")
def read_vatsim():
    global vatsim_data
    return {"vatsim":vatsim_data}