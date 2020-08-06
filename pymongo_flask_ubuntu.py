from flask import Flask, request, render_template, url_for, redirect
from flask_restful import Resource, Api, reqparse
from pymongo import MongoClient
from bson.json_util import dumps
import time

app = Flask(__name__)
api = Api(app)
client = MongoClient('mongodb://localhost:27017')


    
db = client.petDB
collection = db.Crawling_area

client.close()

class Data(Resource):
    def get(self):
        cursor = collection.find()
        parser = reqparse.RequestParser()
        message = dumps(list(cursor))
        parser.add_argument('messages', type=str)
        args = parser.parse_args()
        return {'messages':message}

api.add_resource(Data, '/data')

@app.route('/')
def base():
    return "testing Mongo DB"

@app.route('/threading_test')
def work():
    sec = 1
    #time.sleep(100)
    
    while 1:
        sec += 1
        print("working " + str(sec))
        time.sleep(1)
        if sec == 10:
            break
    
    return redirect(url_for('threading_done'))

@app.route('/threading_done')
def threading_done():
    return "threading done"

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
