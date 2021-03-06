import os
from werkzeug.utils import secure_filename
import boto3
from flask_cors import CORS
from flask_jwt_extended import create_access_token, JWTManager


from flask import Flask, jsonify, request
# from flask_debugtoolbar import DebugToolbarExtension
from flask_bcrypt import Bcrypt
from sqlalchemy.exc import IntegrityError
# from forms import CSRFOnlyForm, EditUserForm, UserAddForm, LoginForm, MessageForm
from models import db, connect_db, User, Action

import dotenv
dotenv.load_dotenv()

CURR_USER_KEY = "curr_user"

BASE_PHOTO_URL="https://s3.us-west-1.amazonaws.com/friender.davis.colin/"

app = Flask(__name__)
CORS(app)

app.config["JWT_SECRET_KEY"] = os.environ['JWT_SECRET_KEY']  # Change this!
jwt = JWTManager(app)

bcrypt= Bcrypt()

# Get DB_URI from environ variable (useful for production/testing) or,
# if not set there, use development local db.
app.config['SQLALCHEMY_DATABASE_URI'] = (os.environ['DATABASE_URL'].replace("postgres://", "postgresql://"))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False
app.config['DEBUG_TB_INTERCEPT_REDIRECTS'] = True
app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
# toolbar = DebugToolbarExtension(app)

connect_db(app)

s3 = boto3.client(
  "s3",
  "us-west-1",
  aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
  aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
)

##############################################################################
# Auth Routes
@app.post('/login')
def login_user():
    """Returns JWT {token:{TOKEN}} on successful login
        returns error object if error
    """
    # print(request.json)

    username = request.json["username"]
    password = request.json["password"]

    isUser = User.authenticate(username, password)
    print("isUser: ", isUser)

    if isUser:
        serialized = User.serialize(isUser)
        access_token = create_access_token(identity=serialized)
        return jsonify(token=access_token)
    else:
        return {"errors": "Username/password is incorrect." }
        # refactor: maybe refactor how errors are handled


##############################################################################
# User Routes
@app.get('/users')
def list_users():
    """Returns JSON list of all user dictionaries.
        {users:[{user1},...]}
    """

    users = User.query.all()
    serialized = [User.serialize(user) for user in users]

    return jsonify(users=serialized)

@app.get('/users/<int:user_id>')
def get_user(user_id):
    """Show user profile."""
    user = User.query.get_or_404(user_id)
    serialize = User.serialize(user)

    return jsonify(user=serialize)


@app.post('/users')
def create_user():
    """Takes is user info as dictionary,
    Adds a new user to the database, and returns added user object.
        {
            "username",
            "first_name",
            "last_name",
            "email",
            "hobbies",
            "interests",
            "zip_code",
            "image"         
        }
    """

    print("request: ", request)

    img = request.files['file']
    if img:
        filename = secure_filename(img.filename)
        s3.upload_fileobj(
            img, 
            os.environ['BUCKET'], 
            filename, 
            ExtraArgs={"ACL":"public-read"}
        )

        #TODO: dont seem to need this to pull image but keeping in case it breaks because we know it can work
        # user_image_url = boto3.client('s3').generate_presigned_url(
        #     ClientMethod='get_object', 
        #     Params={'Bucket': os.environ['BUCKET'], 'Key': user_image_name}, ExpiresIn=6000)
    try:
        user = User.signup(
                username=request.form["username"],
                first_name=request.form["firstName"],
                last_name=request.form["lastName"],
                email=request.form["email"],
                hobbies=request.form["hobbies"],
                interests=request.form["interests"],
                zip_code=request.form["zipCode"],
                image=f"{BASE_PHOTO_URL}{filename}",
                password=request.form["password"],
            )
    except IntegrityError:
        return {"errors": "A user with that username/email already exist." }


    serialized = User.serialize(user)
    access_token = create_access_token(identity=serialized)
    return jsonify(token=access_token)
    # return jsonify(user=serialized)

@app.patch('/users/<int:user_id>')
def edit_user(user_id):
    """Updates a user. Reutrns updated user.
    {
        "username",
        "first_name",
        "last_name",
        "email",
        "hobbies",
        "interests",
        "zip_code",
        "image"         
    }
    """
    user = User.query.get_or_404(user_id)
    newData = request.json
    for key, value in newData.items():
        # user[key] = value
        setattr(user,key,value)
    
    db.session.add(user)
    db.session.commit()
    updated_user = User.query.get_or_404(user_id)
    serialize = User.serialize(updated_user)

    return jsonify(user=serialize)

@app.delete('/users/<int:user_id>')
def delete_user(user_id):
    """Deletes a user. Returns {deleted:user_id}"""
    user = User.query.get_or_404(user_id)

    db.session.delete(user)
    db.session.commit()

    return ({"deleted":user_id})

@app.get('/potentials/<zip_code>')
def get_users_by_zip_code(zip_code):
    """Get users by zipcode. 
    Returns [{
            "username",
            "first_name",
            "last_name",
            "email",
            "hobbies",
            "interests",
            "zip_code",
            "image"         
        }, ...]
    """

    filtered_users = User.query.filter_by(zip_code=zip_code).all()
    serialized = [User.serialize(user) for user in filtered_users]
    # pass in user id
    # derive from user id zip_code of passed in user_id
    # query the Action table here are all the ids of the ppl that user has acted on
    # list of pp yu acted on =Action.query.filter_by(acting_user=user_id).all()
    # User.query.filter_by(zip_code=zip_code, user_id).all()
    return jsonify(users=serialized)

# Auth Routes
@app.post('/action')
def add_action():
    """Returns JSON of action added to DB. Action is LIKE or PASS
        {action:{ACTION}}
        returns error object if error
    """
    acting_user_id = request.json["acting_user_id"]
    targeted_user_id = request.json["targeted_user_id"]
    action = request.json["action"]

    action = Action.add(acting_user_id, targeted_user_id,action)
    print("action added: ", action)

    if action:
        serialized = Action.serialize(action)
        return jsonify(action=serialized)
    else:
        return {"errors": "Unable to process action!" }
        # refactor: maybe refactor how errors are handled

#TODO: make it impossible for somebody to see their own card

@app.get('/potentials/<int:user_id>/<zip_code>')
def get_potential_matches_by_zip_code(user_id,zip_code):
    """Get users by zipcode and filters on people who this person has not yet liked. 
    Returns JSON of user data details 
    [{
            "username",
            "first_name",
            "last_name",
            "email",
            "hobbies",
            "interests",
            "zip_code",
            "image"         
        }, ...]
    """

    # query the Action table here are all the ids of the ppl that user has acted on
    actions = Action.query.filter_by(acting_user_id=user_id).all()
    print(actions)
    # breakpoint()
    acted_upon_users = [action.targeted_user_id for action in actions]
    
    filtered_users = User.query.filter(
        (~(User.user_id.in_(acted_upon_users))),
        zip_code==zip_code
    ).all()


    serialized = [User.serialize(user) for user in filtered_users]
    # pass in user id
    # derive from user id zip_code of passed in user_id
    # User.query.filter_by(zip_code=zip_code, user_id).all()
    return jsonify(users=serialized)

    #TODO: add match functionality to get users we've matched with. requires DB query
    #TODO: add message functionality which will enable users to message their matches
    #TODO: get rid of unused imports and add in docstrings
    #TODO: Add AWS call into its own file
