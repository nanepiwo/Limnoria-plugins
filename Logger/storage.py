
import time
import sqlite3
from threading import RLock

class MessageType:
	privmsg = 0
	notice  = 1
	action  = 2
	join    = 3
	part    = 4
	quit    = 5
	kick    = 6
	nick    = 7
	mode    = 8
	topic   = 9

class LogDB:
	def __init__(self, filename):
		self.conn = sqlite3.connect(filename, 5, 0, None, False)
		self.conn.row_factory = sqlite3.Row
		self.cur = self.conn.cursor()
		self.cur.executescript(
			"CREATE TABLE IF NOT EXISTS sender (\n"
			"	id INTEGER NOT NULL,\n"
			"	nick VARCHAR COLLATE NOCASE,\n"
			"	user VARCHAR COLLATE NOCASE,\n"
			"	host VARCHAR COLLATE NOCASE,\n"
			"	PRIMARY KEY (id)\n"
			");\n"
			"CREATE TABLE IF NOT EXISTS network (\n"
			"	id INTEGER NOT NULL,\n"
			"	name VARCHAR COLLATE NOCASE,\n"
			"	PRIMARY KEY (id)\n"
			");\n"
			"CREATE TABLE IF NOT EXISTS buffer (\n"
			"	id INTEGER NOT NULL,\n"
			"	networkid INTEGER NOT NULL,\n"
			"	name VARCHAR COLLATE NOCASE,\n"
			"	PRIMARY KEY (id),\n"
			"	FOREIGN KEY (networkid) REFERENCES network (id)\n"
			");\n"
			"CREATE TABLE IF NOT EXISTS log (\n"
			"	id INTEGER NOT NULL,\n"
			"	type INTEGER NOT NULL,\n"
			"	timestamp INTEGER NOT NULL,\n"
			"	bufferid INTEGER NOT NULL,\n"
			"	senderid INTEGER NOT NULL,\n"
			"	message VARCHAR,\n"
			"	PRIMARY KEY (id),\n"
			"	FOREIGN KEY (bufferid) REFERENCES buffer (id),\n"
			"	FOREIGN KEY (senderid) REFERENCES sender (id)\n"
			");\n"
			"CREATE INDEX IF NOT EXISTS logBufferTimestamp ON log(bufferid, timestamp);\n"
		)

		self.lock = RLock()

	def __del__(self):
		with self.lock:
			self.cur.close()
			self.conn.commit()
			self.conn.close()

	def commit(self):
		with self.lock:
			self.conn.commit()

	def _getNetwork(self, network):
		return self.cur.execute("""
			SELECT * FROM network WHERE name=?
		""", (network,)).fetchone()

	def getNetwork(self, network, create=True):
		with self.lock:
			row = self._getNetwork(network)
			if row is None and create:
				self.cur.execute("""
					INSERT INTO network (name) VALUES (?)
				""", (network,))
				self.conn.commit()
				row = self._getNetwork(network)
			return row

	def _getBuffer(self, network, name):
		return self.cur.execute("""
			SELECT * FROM buffer
			INNER JOIN network ON network.id=buffer.networkid
			WHERE
				network.name=? AND
				buffer.name=?
		""", (network, name)).fetchone()


	def getBuffer(self, network, name=None, create=True):
		with self.lock:
			row = self._getBuffer(network, name)
			if row is None and create:
				self.cur.execute("""
					INSERT INTO buffer (name, networkid) VALUES (?, ?)
				""", (name, self.getNetwork(network)["id"]))
				self.conn.commit()
				row = self._getBuffer(network, name)
			return row

	def _getSender(self, msg):
		return self.cur.execute("""
			SELECT * FROM sender
			WHERE
				nick=? AND
				user=? AND
				host=?
		""", (msg.nick, msg.user, msg.host)).fetchone()

	def getSender(self, msg, create=True):
		with self.lock:
			row = self._getSender(msg)
			if row is None and create:
				self.cur.execute("""
					INSERT INTO sender (nick, user, host) VALUES (?, ?, ?)
				""", (msg.nick, msg.user, msg.host))
				self.conn.commit()
				row = self._getSender(msg)
			return row

	def add(self, msgtype, network, channel, msg, text):
		with self.lock:
			self.cur.execute("""
				INSERT INTO log (type, timestamp, bufferid, senderid, message)
				VALUES (?, ?, ?, ?, ?)
			""", (
				msgtype,
				int(time.time()),
				self.getBuffer(network, channel)["id"],
				self.getSender(msg)["id"],
				text
			))

	def get(self, bufid, starttime, timelen):
		with self.lock:
			return self.cur.execute("""
					SELECT * FROM log
					INNER JOIN buffer ON buffer.id=log.bufferid
					INNER JOIN network ON network.id=buffer.networkid
					INNER JOIN sender ON sender.id=log.senderid
					WHERE
						log.bufferid=? AND
						log.timestamp BETWEEN ? AND ?
					ORDER BY id ASC
				""", (bufid, starttime, starttime + timelen)).fetchall()

	def getBuffers(self):
		with self.lock:
			return self.cur.execute("""
					SELECT * FROM buffer
					INNER JOIN network ON network.id=buffer.networkid
					ORDER BY id ASC
				""").fetchall()

	def getNetworks(self):
		with self.lock:
			return self.cur.execute("""
					SELECT * FROM network
					ORDER BY id ASC
				""").fetchall()

	def getSenders(self):
		with self.lock:
			return self.cur.execute("""
					SELECT * FROM serder
					ORDER BY id ASC
				""").fetchall()

	def getLast(self, bufid, nick):
		with self.lock:
			return self.cur.execute("""
					SELECT * FROM log
					INNER JOIN sender ON sender.id=log.senderid
					WHERE
						log.bufferid = ? AND
						sender.nick = ?
					ORDER BY id DESC
					LIMIT 1
				""", (bufid, nick)).fetchone()

	def getLastMessage(self, bufid, nick):
		with self.lock:
			return self.cur.execute("""
					SELECT * FROM log
					INNER JOIN sender ON sender.id=log.senderid
					WHERE
						log.bufferid = ? AND
						log.type BETWEEN 0 AND 2 AND
						sender.nick = ?
					ORDER BY id DESC
					LIMIT 1
				""", (bufid, nick)).fetchone()

