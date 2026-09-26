from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class DevLoginForm(FlaskForm):
    email = StringField(
        "Demo identity",
        default="alex@example.invalid",
        validators=[DataRequired(), Length(max=320)],
    )
    submit = SubmitField("Enter the synthetic workspace")


class ConnectForm(FlaskForm):
    accept_disclosure = BooleanField(
        "I understand how Mercury processes mailbox data", validators=[DataRequired()]
    )
    ai_consent = BooleanField(
        "Allow selected message text to be sent to the configured AI provider"
    )
    submit = SubmitField("Connect Gmail")


class EmptyForm(FlaskForm):
    submit = SubmitField("Continue")


class ConfirmDeleteForm(FlaskForm):
    confirmation = StringField("Type DELETE", validators=[DataRequired(), Length(max=16)])
    submit = SubmitField("Delete my Mercury account")


class ReturnPathForm(FlaskForm):
    next = HiddenField()
