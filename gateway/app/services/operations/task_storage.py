from peewee import SqliteDatabase, Model, CharField, IntegerField, TextField
import json

db = SqliteDatabase("tasks.db")

class Task(Model):
    task_id = CharField(primary_key=True)
    priority = IntegerField()
    task_type = CharField()
    payload = TextField()
    user_id = CharField()
    status = CharField()
    result = TextField(null=True)

    class Meta:
        database = db

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "priority": self.priority,
            "task_type": self.task_type,
            "payload": json.loads(self.payload),
            "user_id": self.user_id,
            "status": self.status,
            "result": json.loads(self.result) if self.result else None
        }

def init_db():
    if db.is_closed():
        db.connect()
    db.create_tables([Task], safe=True)