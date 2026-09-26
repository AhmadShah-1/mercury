from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class BucketForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(min=1, max=80)])
    purpose = StringField("Purpose", validators=[Length(max=240)])
    submit = SubmitField("Save bucket")


class MoveThreadForm(FlaskForm):
    bucket_id = SelectField("Move to", choices=[], validators=[DataRequired()])
    submit = SubmitField("Move")


class ActionForm(FlaskForm):
    status = SelectField(
        "Action status",
        choices=[("handled", "Mark handled"), ("dismissed", "Not an action"), ("open", "Reopen")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Update")


class SenderRuleForm(FlaskForm):
    sender_address = StringField("Exact sender", validators=[DataRequired(), Length(max=320)])
    bucket_id = SelectField("Destination", choices=[], validators=[DataRequired()])
    enabled = BooleanField("Enabled", default=True)
    submit = SubmitField("Save rule")


class MergeForm(FlaskForm):
    destination_id = SelectField("Merge into", choices=[], validators=[DataRequired()])
    confirm = BooleanField("I reviewed the affected thread count", validators=[DataRequired()])
    submit = SubmitField("Merge buckets")
