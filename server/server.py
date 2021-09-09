import os
import uuid
import smtplib
import json
import functools
import face_recognition


from dataclasses import dataclass
from datetime import datetime

from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   send_from_directory, abort)
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.curdir, 'uploads')
app.config['SECRET_KEY'] = "WGRwwA>L<](]c&z^umkHhC78?^(/ws'7"
app.config['DEBUG'] = 1

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///face_recognizer.db'

CONFIG_FILE = 'settings.conf'

db = SQLAlchemy(app)
sio = SocketIO(app)


def mail_serv(message, location):

    config_file = open(CONFIG_FILE, 'r')
    config = json.loads(config_file.read())
    config_file.close()
    mail_id = config['EMAIL_ID']
    password = config['PASSWORD']
    receiver = config['RECEIVER']
    # location = config['LOCATION']

    s = smtplib.SMTP('smtp.gmail.com', 587)

    s.starttls()
    s.login(mail_id, password)
    message += f'\n\nLocation: {location}'
    try:
        s.sendmail(mail_id, receiver, message)
    except Exception:
        pass

    s.quit()


@dataclass
class Person(db.Model):
    id: int
    name: str
    file: str
    disc: str
    live_track: bool
    date: str

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    file = db.Column(db.String(100))
    disc = db.Column(db.String(500))
    live_track = db.Column(db.Boolean)
    date = db.Column(db.DateTime)


@dataclass
class Location(db.Model):
    id: int
    uid: str
    cam_no: int
    place: str
    discription: str

    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(128))
    cam_no = db.Column(db.Integer)
    place = db.Column(db.String(1000))
    discription = db.Column(db.String(1000))


class FaceRecognizerIndex(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    time = db.Column(db.DateTime)
    person_id = db.Column(db.Integer, db.ForeignKey(
        'person.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey(
        'location.id'), nullable=False)


class OnlineSystems(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    sid = db.Column(db.String(1000))
    time = db.Column(db.DateTime)
    location_id = db.Column(db.Integer, db.ForeignKey(
        'location.id'), nullable=False)


@app.route('/')
def index():
    persons = Person.query.all()
    title = "Home | God's Eye"
    return render_template('index.html', photo_list=persons, title=title)


@app.route('/get_data')
def photots():
    persons = Person.query.all()
    print(persons)
    return jsonify(persons)


@app.route('/new')
def new_upload():
    title = "Add a person | God's Eye"
    return render_template('upload-form.html', title=title)


@app.route('/upload', methods=["POST"])
def upload_photo():

    if 'person' not in request.files:
        flash('No file attached')
        return redirect(request.url)

    file = request.files['person']
    name = request.form['name']
    discription = request.form['disc']

    live_track = request.form.get("track", False)
    if live_track == "True":
        live_track = True
    print(request.form)
    filename = str(uuid.uuid4()) + '.' + \
        secure_filename(file.filename).split('.')[-1]
    print(discription)
    if file.filename == '':
        flash('No selected file')
        return redirect(request.url)
    if file:
        # filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    person = Person(name=name, disc=discription,
                    file=filename, date=datetime.now(), live_track=live_track)
    db.session.add(person)
    db.session.commit()

    image = face_recognition.load_image_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    face_location = face_recognition.face_locations(image)
    face_vector = face_recognition.face_encodings(image, face_location)[0]

    emit("database_updated", broadcast=True, namespace="/")
    emit("get_past_record", {"id": person.id, "face_encoding": list(face_vector)}, broadcast=True, namespace="/")
    print(person)
    return redirect('/')


@app.route('/view/<int:table_id>')
def view_person(table_id):
    person = Person.query.get_or_404(table_id)
    face_index = db.session.query(FaceRecognizerIndex).filter(FaceRecognizerIndex.person_id == table_id).all()
    title = "View person | God's Eye"
    face_recognition_table = []

    for found in face_index:
        face_dict = {}
        location = Location.query.get(found.location_id)
        face_dict["id"] = found.id
        face_dict["place"] = location.place
        face_dict["cam_no"] = location.cam_no
        face_dict["time"] = found.time
        face_recognition_table.append(face_dict)

    return render_template('detail-view.html', person=person, face_recognition_table=face_recognition_table, title=title)


@app.route('/update_person/<id>', methods=["GET", "POST"])
def update_person(id):
    person = Person.query.get_or_404(id)
    data = request.form
    title = "Updating info | God's Eye"
    if request.method == "POST":
        person.name = data["name"]
        person.disc = data["disc"]
        live_track = request.form.get("track", False)
        if live_track == "True":
            live_track = True
        person.live_track = live_track
        db.session.commit()
        return redirect(f"/view/{id}")
    return render_template("upload-form.html", person=person, id=id, update=True, title=title)


@app.route('/delete_person/<id>')
def delete_person(id):
    try:
        person = Person.query.get_or_404(id)
        db.session.delete(person)
        face_index = db.session.query(FaceRecognizerIndex).filter(FaceRecognizerIndex.person_id == id).all()
        file_name = f'./uploads/{person.file}'
        if os.path.exists(file_name):
            os.remove(file_name)
        else:
            print("The file does not exist")
        for found in face_index:
            db.session.delete(found)
        db.session.commit()
        emit("database_updated", broadcast=True, namespace="/")

        return redirect('/')
    except Exception as e:
        print(e)
        return abort(404)


@app.route('/new_location', methods=["GET", "POST"])
def new_location():

    title = "Add new Location | God's Eye"

    if(request.method == "POST"):
        data = request.form
        title = "Location is added | God's Eye"
        print(data)
        uid = str(uuid.uuid4())
        cam_no = data["cam_no"]
        place = data["place"]
        discription = data["disc"]
        location = Location(uid=uid, cam_no=cam_no, place=place, discription=discription)
        db.session.add(location)
        db.session.commit()

        return render_template('new_location.html', uid=uid,  title=title)

    return render_template('new_location.html',  title=title)


@app.route('/view_location')
def view_location():
    locations = Location.query.all()
    title = "View Locations | God's Eye"
    return render_template("view_location.html", location=locations,  title=title)


@app.route('/view_online')
def view_online():
    title = "View Online Systems | God's Eye"
    online_system = OnlineSystems.query.all()
    online_dict = []
    for online in online_system:
        loc_dict = {}
        locat = Location.query.get(online.location_id)
        loc_dict["id"] = online.id
        loc_dict["place"] = locat.place
        loc_dict["cam_no"] = locat.cam_no
        loc_dict["time"] = online.time
        online_dict.append(loc_dict)

    return render_template("online_system.html", location=online_dict, title=title)


@app.route('/update_location/<id>')
def update_location(id):
    location = Location.query.get(id)
    title = "Update Location | God's Eye"
    data = request.form
    if request.method == "POST":
        location.place = data["place"]
        location.cam_no = data["cam_no"]
        location.discription = data["discription"]
        db.session.commit()
        return redirect("/view_location")
    return render_template("new_location.html", location=location, title=title, update=True)


@app.route('/delete_location/<id>')
def delete_location(id):
    try:
        location = Location.query.get_or_404(id)
        face_index = db.session.query(FaceRecognizerIndex).filter(FaceRecognizerIndex.location_id == id).all()
        db.session.delete(location)
        for face in face_index:
            db.session.delete(face)
        db.session.commit()
        return redirect('/view_location')

    except Exception as e:

        print(e)
        return abort(404)


# @app.route("/person_found", methods=["POST"])
@sio.event
def person_found(data):
    # data = request.json
    try:
        print(f"request received with ... {data}")
        # mail_serv(data["person"], data["location"])
        location = db.session.query(Location).filter(Location.uid == data["auth_token"]).first()

        face_index = FaceRecognizerIndex(time=datetime.now(), location_id=location.id, person_id=data["id"])
        db.session.add(face_index)
        db.session.commit()
        print(location)
        print(face_index)
        print("success", 200)
    except Exception as e:
        print(e)
        print("failed", 502)


@app.route('/uploads/<path:path>')
def get_photo(path):
    return send_from_directory('uploads', path)


@sio.event
def connect():
    # print(data)
    print('connection established', request.sid)


@sio.event
def auth_event(data):
    print('auth_event', request.sid)
    location = db.session.query(Location).filter(Location.uid == data["auth_token"]).first()

    if location is not None:
        online = OnlineSystems(sid=request.sid, time=datetime.now(), location_id=location.id)
        db.session.add(online)
        db.session.commit()
    else:
        print("invalid auth token")


@sio.event
def update_past_record(data):
    try:
        print(f"request received with ... {data}")
        # mail_serv(data["person"], data["location"])
        location = db.session.query(Location).filter(Location.uid == data["auth_token"]).first()

        face_index = FaceRecognizerIndex(time=data["time"], location_id=location.id, person_id=data["id"])
        db.session.add(face_index)
        db.session.commit()
        print(location)
        print(face_index)
        print("success", 200)
    except Exception as e:
        print(e)
        print("failed", 502)


@sio.event
def disconnect():
    try:
        online = db.session.query(OnlineSystems).filter(OnlineSystems.sid == request.sid).first()
        db.session.delete(online)
        db.session.commit()
        print('disconnect ', request.sid)
    except Exception as e:
        print(e)
        print("failed to delete sid - ", request.sid)


if __name__ == "__main__":
    if not os.path.exists("uploads"):
        os.mkdir("uploads")
    sio.run(app)
