from app import (
    mythic,
    db_objects,
    links,
    nginx_port,
    listen_port,
    mythic_admin_password,
    mythic_admin_user,
    default_operation_name,
)
from sanic.response import json, redirect
from sanic import response
from sanic.exceptions import (
    NotFound,
    Unauthorized,
    MethodNotSupported,
    SanicException,
    RequestTimeout,
)
from jinja2 import Environment, PackageLoader
from app.database_models.model import (
    Operator,
    Operation,
    OperatorOperation,
    ATTACK,
    Artifact,
)
from app.forms.loginform import LoginForm, RegistrationForm
import datetime
import app.crypto as crypto
from sanic_jwt import BaseEndpoint, utils, exceptions
from sanic_jwt.decorators import scoped, inject_user
import ujson as js
from ipaddress import ip_address
from app.routes.authentication import invalidate_refresh_token
import app.database_models.model as db_model
from sanic.log import logger
from app.api.browserscript_api import set_default_scripts
from uuid import uuid4


env = Environment(loader=PackageLoader("app", "templates"), autoescape=True)


async def respect_pivot(my_links, request):
    # given the links dictionary, update the server_ip and server_port to match what was received
    # this will allow people using pivots (127.0.0.1:8888) to still access things going through to IP:other_port
    updated_links = my_links
    host_field = request.host.split(":")
    if len(host_field) == 1:
        server_ip = host_field[0]
        if 'x-forwarded-port' in request.headers:
            server_port = request.headers["x-forwarded-port"]
        else:
            if request.scheme == "https":
                server_port = nginx_port
            else:
                server_port = listen_port
    else:
        server_ip = host_field[0]
        server_port = host_field[1]
    updated_links["server_ip"] = server_ip
    updated_links["server_port"] = server_port
    updated_links["login"] = "{}://{}/login".format(request.scheme, request.host)
    updated_links["register"] = "{}://{}/register".format(request.scheme, request.host)
    return updated_links


async def getSchemes(request):
    if 'x-forwarded-proto' in request.headers:
        if request.headers['x-forwarded-proto'] == "http":
            return {"http": "http", "ws": "ws"}
        else:
            return {"http": "https", "ws": "wss"}
    if request.scheme == "http":
        return {"http": "http", "ws": "ws"}
    else:
        return {"http": "https", "ws": "wss"}


@mythic.route("/")
@inject_user()
@scoped("auth:user")
async def index(request, user):
    template = env.get_template("main_page.html")
    content = template.render(
        name=user["username"],
        links=await respect_pivot(links, request),
        current_operation=user["current_operation"],
        config=user["ui_config"],
        view_utc_time=user["view_utc_time"],
        ** await getSchemes(request)
    )

    return response.html(content)


class Login(BaseEndpoint):
    async def get(self, request):
        form = LoginForm(request)
        errors = {}
        successful_creation = request.args.pop("success", False)
        errors["username_errors"] = "<br>".join(form.username.errors)
        errors["password_errors"] = "<br>".join(form.password.errors)
        template = env.get_template("login.html")
        content = template.render(
            links=await respect_pivot(links, request),
            form=form,
            errors=errors,
            successful_creation=successful_creation,
            config={},
            view_utc_time=False,
            ** await getSchemes(request)
        )
        return response.html(content)

    async def post(self, request):
        form = LoginForm(request)
        errors = {}
        if form.validate():
            username = form.username.data
            password = form.password.data
            try:
                query = await db_model.operator_query()
                user = await db_objects.get(query, username=username)
                if await user.check_password(password):
                    if not user.active:
                        form.username.errors = ["Account is not active, cannot log in"]
                    else:
                        try:
                            user.last_login = datetime.datetime.utcnow()
                            await db_objects.update(
                                user
                            )  # update the last login time to be now
                            if user.current_operation is not None:
                                # update that operations' event log that the user just signed in
                                await db_objects.create(
                                    db_model.OperationEventLog,
                                    operator=None,
                                    operation=user.current_operation,
                                    message="{} signed in".format(user.username),
                                )
                            (
                                access_token,
                                output,
                            ) = await self.responses.get_access_token_output(
                                request,
                                {"user_id": user.id, "auth": "cookie"},
                                self.config,
                                self.instance,
                            )
                            refresh_token = (
                                await self.instance.auth.generate_refresh_token(
                                    request, {"user_id": user.id, "auth": "cookie"}
                                )
                            )
                            output.update(
                                {self.config.refresh_token_name(): refresh_token}
                            )
                            template = env.get_template("login.html")
                            content = template.render(
                                links=await respect_pivot(links, request),
                                form=form,
                                errors=errors,
                                access_token=access_token,
                                ** await getSchemes(request),
                                refresh_token=refresh_token,
                                config={},
                                view_utc_time=False,
                            )
                            resp = response.html(content)
                            # resp = response.redirect("/")
                            resp.cookies[
                                self.config.cookie_access_token_name()
                            ] = access_token
                            resp.cookies[self.config.cookie_access_token_name()][
                                "httponly"
                            ] = True
                            resp.cookies[
                                self.config.cookie_refresh_token_name()
                            ] = refresh_token
                            resp.cookies[self.config.cookie_refresh_token_name()][
                                "httponly"
                            ] = True
                            return resp
                        except Exception as e:
                            logger.error("post login error:" + str(e))
                else:
                    form.username.errors = ["Username or password invalid"]
            except Exception as e:
                logger.info(f"Unable to login as the user {username}. " + str(e))
                form.username.errors = ["Username or password invalid"]
        errors["username_errors"] = "<br>".join(form.username.errors)
        errors["password_errors"] = "<br>".join(form.password.errors)
        template = env.get_template("login.html")
        content = template.render(
            links=await respect_pivot(links, request),
            form=form,
            errors=errors,
            config={},
            view_utc_time=False,
            ** await getSchemes(request)
        )
        return response.html(content)


class Register(BaseEndpoint):
    async def get(self, request, *args, **kwargs):
        errors = {}
        form = RegistrationForm(request)
        template = env.get_template("register.html")
        content = template.render(
            links=await respect_pivot(links, request),
            form=form,
            errors=errors,
            config={},
            view_utc_time=False,
            ** await getSchemes(request)
        )
        return response.html(content)

    async def post(self, request, *args, **kwargs):
        errors = {}
        form = RegistrationForm(request)
        if form.validate():
            username = form.username.data
            salt = str(uuid4())
            password = await crypto.hash_SHA512(salt + form.password.data)
            # we need to create a new user
            try:
                user = await db_objects.create(
                    Operator, username=username, password=password, admin=False, active=False, salt=salt
                )
                query = await db_model.operation_query()
                operations = await db_objects.execute(query)
                for o in operations:
                    await db_objects.create(
                        db_model.OperationEventLog,
                        operator=None,
                        operation=o,
                        message="New user {} created".format(user.username),
                    )
                await set_default_scripts(user)
                return response.redirect("/login?success=true")
            except Exception as e:
                # failed to insert into database
                logger.error("Failed to insert user into database: " + str(e))
                form.username.errors = ["Failed to create user"]
        errors["username_errors"] = "<br>".join(form.username.errors)
        template = env.get_template("register.html")
        content = template.render(
            links=await respect_pivot(links, request),
            form=form,
            errors=errors,
            successful_creation=False,
            config={},
            view_utc_time=False,
            ** await getSchemes(request)
        )
        return response.html(content)


class UIRefresh(BaseEndpoint):
    async def get(self, request, *args, **kwargs):
        # go here if we're in the browser and our JWT expires so we can update it and continue on
        payload = self.instance.auth.extract_payload(request, verify=True)
        try:
            user = await utils.call(
                self.instance.auth.retrieve_user, request, payload=payload
            )
        except exceptions.MeEndpointNotSetup:
            raise exceptions.RefreshTokenNotImplemented

        user_id = await self.instance.auth._get_user_id(user)
        refresh_token = await utils.call(
            self.instance.auth.retrieve_refresh_token,
            request=request,
            user_id=user_id,
        )
        if isinstance(refresh_token, bytes):
            refresh_token = refresh_token.decode("utf-8")
        token = await self.instance.auth.retrieve_refresh_token_from_request(request)

        if refresh_token != token:
            raise exceptions.AuthenticationFailed()

        access_token, output = await self.responses.get_access_token_output(
            request, user, self.config, self.instance
        )
        redirect_to = (
            request.headers["referer"] if "referer" in request.headers else "/"
        )
        resp = response.redirect(redirect_to)
        resp.cookies[self.config.cookie_access_token_name()] = access_token
        resp.cookies[self.config.cookie_access_token_name()]["httponly"] = True
        return resp


@mythic.route("/settings", methods=["GET"])
@inject_user()
@scoped("auth:user")
async def settings(request, user):
    template = env.get_template("settings.html")
    try:
        content = template.render(
            links=await respect_pivot(links, request),
            name=user["username"],
            ** await getSchemes(request),
            config=user["ui_config"],
            view_utc_time=user["view_utc_time"],
        )
        return response.html(content)
    except Exception as e:
        logger.error(str(e))
        return json({"status": "error", "error": "Failed to find operator"})


@mythic.route("/logout")
@inject_user()
@scoped("auth:user")
async def logout(request, user):
    resp = response.redirect("/login")
    del resp.cookies["access_token"]
    del resp.cookies["refresh_token"]
    query = await db_model.operator_query()
    operator = await db_objects.get(query, id=user["id"])
    if operator.current_operation is not None:
        await db_objects.create(
            db_model.OperationEventLog,
            operator=None,
            operation=operator.current_operation,
            message="{} signed out".format(operator.username),
        )
    # now actually invalidate tokens
    await invalidate_refresh_token(user["id"])
    return resp


@mythic.exception(NotFound)
async def handler_404(request, exception):
    return json({"status": "error", "error": "Not Found"}, status=404)


@mythic.exception(MethodNotSupported)
async def handler_405(request, exception):
    return json({"status": "error", "error": "Session Expired, refresh"}, status=405)


@mythic.exception(RequestTimeout)
def request_timeout(request, exception):
    return json({"status": "error", "error": "request timeout"})


@mythic.exception(exceptions.AuthenticationFailed)
async def handler_auth_failed(request, exception):
    if "/new" in request.path or "webhook" in request.path or "/auth" in request.path:
        return json({"status": "error", "error": "Authentication failed", "message": "access-denied", "code": "access-denied"}, status=401)
    else:
        return response.redirect("/login")


@mythic.exception(Unauthorized)
async def handler_auth_failed(request, exception):
    if "/new" in request.path or "webhook" in request.path:
        return json({"status": "error", "error": "Authentication failed", "message": "Unauthorized", "code": "forbidden"}, status=403)
    else:
        return response.redirect("/login")


@mythic.exception(SanicException)
def catch_all(request, exception):

    logger.exception(
        "Caught random exception within Mythic: {}, {}".format(exception, str(request))
    )
    return json({"status": "error", "error": "Mythic encountered an error"}, status=500)


@mythic.middleware("request")
async def check_ips(request):
    if (
        request.path in ["/login", "/register", "/auth", "/"]
        or "/payloads/download/" in request.path
    ):
        ip = ip_address(request.ip)
        for block in mythic.config["ALLOWED_IPS"]:
            if ip in block:
                return
        return json({"error": "Not Found"}, status=404)


@mythic.listener("before_server_start")
async def setup_initial_info(app, loop):
    await initial_setup()


async def initial_setup():
    # create mythic_admin
    operators = await db_objects.execute(Operator.select())
    if len(operators) != 0:
        logger.info("Users already exist, aborting initial install")
        return
    salt = str(uuid4())
    password = await crypto.hash_SHA512(salt + mythic_admin_password)
    admin, created = await db_objects.get_or_create(
        Operator, username=mythic_admin_user, password=password, admin=True, active=True, salt=salt
    )
    logger.info("Created Admin")
    # create default operation
    operation, created = await db_objects.get_or_create(
        Operation,
        name=default_operation_name,
        admin=admin,
        complete=False,
    )
    logger.info("Created Operation")
    await db_objects.get_or_create(
        OperatorOperation, operator=admin, operation=operation
    )
    admin.current_operation = operation
    await db_objects.update(admin)
    logger.info("Registered Admin with the default operation")
    logger.info("Started parsing ATT&CK data...")
    file = open("./app/default_files/other_info/attack.json", "r")
    attack = js.load(file)  # this is a lot of data and might take a hot second to load
    for obj in attack["techniques"]:
        await db_objects.create(ATTACK, **obj)
    file.close()
    logger.info("Created all ATT&CK entries")
    file = open("./app/default_files/other_info/artifacts.json", "r")
    artifacts_file = js.load(file)
    for artifact in artifacts_file["artifacts"]:
        await db_objects.get_or_create(
            Artifact, name=artifact["name"], description=artifact["description"]
        )
    file.close()
    logger.info("Created all base artifacts")
    logger.info("Successfully finished initial setup")


# /static serves out static images and files
mythic.static("/static", "./app/static")
mythic.static("/favicon.ico", "./app/static/favicon.ico")
# / serves out the payloads we wish to host, make user supply a path they want to use, or just use file name
mythic.static("/", "./app/payloads/operations/_hosting_dir")
mythic.static("/strict_time.png", "./app/static/strict_time.png", name="strict_time")
mythic.static(
    "/grouped_output.png", "./app/static/grouped_output.png", name="grouped_output"
)
mythic.static(
    "/no_cmd_output.png", "./app/static/no_cmd_output.png", name="no_cmd_output"
)
mythic.static("/add_comment.png", "./app/static/add_comment.png", name="add_comment")

# add links to the routes in this file at the bottom
links["index"] = mythic.url_for("index")
links["login"] = links["WEB_BASE"] + "/login"
links["logout"] = mythic.url_for("logout")
links["register"] = links["WEB_BASE"] + "/register"
links["settings"] = mythic.url_for("settings")
