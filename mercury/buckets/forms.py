from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, SelectMultipleField, StringField, SubmitField
from wtforms.validators import AnyOf, DataRequired, Length, Optional


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


class PlaceBucketForm(FlaskForm):
    # "" takes the bucket out of its crate; "new" starts a crate. Choices are the owner's crates.
    crate_id = SelectField("Crate", choices=[], validate_choice=True)
    with_bucket_id = SelectField("With bucket", choices=[], validators=[Optional()])
    name = StringField("Crate name", validators=[Optional(), Length(max=80)])
    # Only Undo sends this, to hand a bucket Mercury had filed back to automatic filing.
    restore = StringField("Restore", validators=[Optional(), AnyOf(["auto"])])


class FavoriteForm(FlaskForm):
    favorite = StringField("Favorite", validators=[AnyOf(["0", "1"])])


class NewCrateForm(FlaskForm):
    name = StringField("Crate name", validators=[Optional(), Length(max=80)])
    bucket_ids = SelectMultipleField("Buckets", choices=[], validators=[DataRequired()])


class RenameCrateForm(FlaskForm):
    name = StringField("Crate name", validators=[DataRequired(), Length(min=1, max=80)])


class CombineCratesForm(FlaskForm):
    target_id = SelectField("Combine into", choices=[], validators=[DataRequired()])
