import json
import threading
import time

import cv2
import face_recognition
import numpy as np
import requests
import socketio
import uuid

from datetime import datetime
from PIL import Image

SERVER_RUNNING = True
CONFIG_FILE = 'settings.conf'

config_file = open(CONFIG_FILE, 'r')
config = json.loads(config_file.read())

auth_token = config['auth_token']

SERVER_URL = config['server_url']
DEBUG = config['debug']
SOURCE = config['source']
Tolarance = config['tolarance']

known_face_encodings = []
known_face_names = []
known_person_id = []

Traker_dict = {}
Traker_list = []
Traker_names = []

sio = socketio.Client()


def socket_comm():
    sio.connect('http://127.0.0.1:5000')
    sio.wait()


@sio.event
def connect():
    print('connection established')
    config_file = open(CONFIG_FILE, 'r')
    config = json.loads(config_file.read())
    auth_token = config['auth_token']
    time.sleep(5)
    sio.emit("auth_event", {"auth_token": auth_token})


@sio.event
def database_updated():
    cs_thread = threading.Thread(target=check_server)

    # start the threads
    cs_thread.start()

    # join the threads
    cs_thread.join()
    print("database updated")


@sio.event
def get_past_record(data):
    print(f"Id -> {data['id']} face_encoding -> {data['face_encoding']}")
    result = face_recognition.compare_faces(Traker_list, np.asarry(data['face_encoding']))
    distance = face_recognition.face_distance(Traker_list, np.asarry(data['face_encoding']))
    best_match_index = np.argmin(distance)

    if result[best_match_index]:
        name = Traker_names[best_match_index]
        records = Traker_dict[name]
        for stamp in records["time"]:
            sio.emit("update_past_record", {"id": data["id"], "time": stamp, "auth_token": auth_token})


def check_server():

    url = SERVER_URL+'get_data'
    req = requests.get(url).text
    print('send request to the server')

    with open('database/data.json', 'w') as json_data:
        json_data.write(req)

    content = json.loads(req)

    for data in content:
        img_url = SERVER_URL + 'uploads/' + data['file']
        img = requests.get(img_url).content
        print(f'downloading {data["file"]}')
        with open(f"server_images/{data['file']}", 'wb') as img_file:
            img_file.write(img)
    load_data()


def load_data():
    # Load a sample picture and learn how to recognize it.
    global Traker_dict
    json_data = open('database/database.json')
    Traker_dict = json.loads(''.join(json_data.readlines()))
    json_data.close()

    with open('database/data.json') as json_data:

        content = json.loads(''.join(json_data.readlines()))

        for data in content:
            person_image = face_recognition.load_image_file(f"server_images/{data['file']}")
            person_face_encoding = face_recognition.face_encodings(person_image)[0]
            if data["live_track"]:
                known_face_encodings.append(person_face_encoding)
                known_face_names.append(data['name'])
                known_person_id.append(data['id'])
            if data["name"] not in Traker_dict:
                Traker_dict[data['name']] = {"face_vector": list(person_face_encoding), "time": []}
            Traker_list.append(person_face_encoding)
            Traker_names.append(data['name'])


def create_new_record(face_encoding, face_location, frame):
    name = str(uuid.uuid4()) + ".png"
    Traker_dict[name] = {"face_vector": list(face_encoding), "time": [str(datetime.now()), ]}
    Traker_list.append(face_encoding)
    Traker_names.append(name)

    top, right, bottom, left = face_location
    face_image = frame[top:bottom, left:right]
    pil_image = Image.fromarray(face_image)
    pil_image.save(f"client_images/{name}")


def update_record(name, update):
    try:
        Traker_dict[name]["time"].append(update)
    except Exception as e:
        print(e)


def face_recognizer():

    video_capture = cv2.VideoCapture(SOURCE)

    # Initialize some variables
    face_locations = []
    face_encodings = []
    face_names = []
    process_this_frame = True

    while True:
        # Grab a single frame of video
        ret, frame = video_capture.read()

        # Resize frame of video to 1/4 size for faster face recognition processing
        small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)

        # Convert the image from BGR color (which OpenCV uses) to RGB color (which face_recognition uses)
        rgb_small_frame = small_frame[:, :, ::-1]

        # Only process every other frame of video to save time
        if process_this_frame:
            # Find all the faces and face encodings in the current frame of video
            face_locations = face_recognition.face_locations(rgb_small_frame)
            face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

            face_names = []
            for face_encoding, face_location in zip(face_encodings, face_locations):
                # See if the face is a match for the known face(s)

                name = "Unknown"
                if len(Traker_list) != 0:
                    traker_match = face_recognition.compare_faces(Traker_list, face_encoding, tolerance = Tolarance)
                    traker_fd = face_recognition.face_distance(Traker_list, face_encoding)
                    traker_bmi = np.argmin(traker_fd)

                    if traker_match[traker_bmi]:
                        name = Traker_names[traker_bmi]
                        update_record(name, str(datetime.now()))
                    else:
                        create_new_record(face_encoding, face_location, rgb_small_frame)
                else:
                    create_new_record(face_encoding, face_location, rgb_small_frame)
                if len(known_face_encodings) != 0:
                    matches = face_recognition.compare_faces(known_face_encodings, face_encoding, tolerance = Tolarance)
                    face_distances = face_recognition.face_distance(known_face_encodings, face_encoding)
                    best_match_index = np.argmin(face_distances)

                    if matches[best_match_index]:
                        name = known_face_names[best_match_index]
                        id = known_person_id[best_match_index]
                        print(f"Found {name} on the frame")

                        if not DEBUG:
                            print("sending socket request ...")
                            # requests.post(PERSON_FOUND_URL, json={"id": id, "name": name, "Location": auth_token})
                            sio.emit("person_found", {"id": id, "name": name, "auth_token": auth_token})

                face_names.append(name)

        process_this_frame = not process_this_frame

        # Display the results
        for (top, right, bottom, left), name in zip(face_locations, face_names):
            # Scale back up face locations since the frame we detected in was scaled to 1/4 size
            top *= 2
            right *= 2
            bottom *= 2
            left *= 2

            # Draw a box around the face
            cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)

            # Draw a label with a name below the face
            cv2.rectangle(frame, (left, bottom - 35),
                          (right, bottom), (0, 0, 255), cv2.FILLED)
            font = cv2.FONT_HERSHEY_DUPLEX
            cv2.putText(frame, name, (left + 6, bottom - 6),
                        font, 0.75, (255, 255, 255), 1)

        # Display the resulting image
        cv2.imshow("God's Eye", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            with open("database/database.json", "w") as db:
                db.write(json.dumps(Traker_dict))
            break

    video_capture.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    # download initial data
    if SERVER_RUNNING:
        check_server()
    else:
        load_data()

    sc_thread = threading.Thread(target=socket_comm)
    fr_thread = threading.Thread(target=face_recognizer)

    # start the threads
    sc_thread.start()
    time.sleep(5)
    fr_thread.start()

    # join the threads
    sc_thread.join()
    fr_thread.join()
