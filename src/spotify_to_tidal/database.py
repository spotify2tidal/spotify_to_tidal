import datetime
import os

from typing import Union
import sqlalchemy
from sqlalchemy import Table, Column, String, DateTime, MetaData, insert, select, update, delete


class Database:
    def __init__(self, filename: os.PathLike='.cache.db'):
        self.engine = sqlalchemy.create_engine(f"sqlite:///{filename}")
        meta = MetaData()
        self.match_failures = Table('match_failures', meta,
                                    Column('track_id', String,
                                           primary_key=True),
                                    Column('insert_time', DateTime),
                                    Column('next_retry', DateTime),
                                    sqlite_autoincrement=False)
        meta.create_all(self.engine)

    def _get_next_retry_time(self, insert_time: Union[datetime.datetime, datetime.timedelta]=None) -> datetime.datetime:
        if insert_time:
            # double interval on each retry
            interval = 2 * (datetime.datetime.now() - insert_time)
        else:
            interval = datetime.timedelta(days=7)
        return datetime.datetime.now() + interval

    def cache_match_failure(self, track_id: int) -> None:
        """ notifies that matching failed for the given track_id """
        fetch_statement = select(self.match_failures).where(
            self.match_failures.c.track_id == track_id)
        connection: sqlalchemy.engine.Connection
        with self.engine.connect() as connection:
            with connection.begin():
                # Either update the next_retry time if track_id already exists, otherwise create a new entry
                existing_failure = connection.execute(
                    fetch_statement).fetchone()
                if existing_failure:
                    update_statement = update(self.match_failures).where(
                        self.match_failures.c.track_id == track_id).values(next_retry=self._get_next_retry_time())
                    connection.execute(update_statement)
                else:
                    connection.execute(insert(self.match_failures), {
                                       "track_id": track_id, "insert_time": datetime.datetime.now(), "next_retry": self._get_next_retry_time()})

    def has_match_failure(self, track_id: int) -> bool:
        """ checks if there was a recent search for which matching failed with the given track_id """
        statement = select(self.match_failures.c.next_retry).where(
            self.match_failures.c.track_id == track_id)
        with self.engine.connect() as connection:
            match_failure = connection.execute(statement).fetchone()
            if match_failure:
                return match_failure.next_retry > datetime.datetime.now()
            return False

    def remove_match_failure(self, track_id: int) -> None:
        """ removes match failure from the database """
        statement = delete(self.match_failures).where(
            self.match_failures.c.track_id == track_id)
        connection: sqlalchemy.engine.Connection
        with self.engine.connect() as connection:
            with connection.begin():
                connection.execute(statement)


# Main singleton instance
failure_cache = Database()
