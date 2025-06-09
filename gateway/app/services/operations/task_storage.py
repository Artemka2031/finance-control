import json
from peewee import SqliteDatabase, Model, CharField, IntegerField, TextField

from ..core.config import DATABASE_PATH, log

# Один файл - одно соединение, разрешаем использование из разных потоков
db = SqliteDatabase(
    DATABASE_PATH,
    pragmas={
        "journal_mode": "wal",
        "foreign_keys": 1,
    },
    check_same_thread=False,
)


class Task(Model):
    task_id  = CharField(primary_key=True)
    priority = IntegerField()
    task_type = CharField()
    payload  = TextField()
    user_id  = CharField()
    status   = CharField()
    result   = TextField(null=True)

    class Meta:
        database   = db
        table_name = "task"   # явное имя — чтобы не путаться с pluralisation

    def to_dict(self):
        return {
            "task_id" : self.task_id,
            "priority": self.priority,
            "task_type": self.task_type,
            "payload" : json.loads(self.payload),
            "user_id" : self.user_id,
            "status"  : self.status,
            "result"  : json.loads(self.result) if self.result else None,
        }


def init_db() -> None:
    """Создаёт файл БД и таблицу task, если их ещё нет (idempotent)."""
    if db.is_closed():
        db.connect(reuse_if_open=True)
    db.create_tables([Task], safe=True)
    log.info(f"Database initialized at {DATABASE_PATH}")


# Гарантируем, что таблица есть уже при импорте модуля
init_db()
