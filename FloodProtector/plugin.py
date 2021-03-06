import re
import time
import string  # For string.ascii_lowercase (detecting CAPS floods)

import supybot.conf as conf
import supybot.ircutils as ircutils
import supybot.ircmsgs as ircmsgs
import supybot.ircdb as ircdb
from supybot.commands import *
import supybot.callbacks as callbacks
import supybot.schedule as schedule
from supybot.i18n import PluginInternationalization, internationalizeDocstring
_ = PluginInternationalization('FloodProtector')


class FloodProtector(callbacks.Plugin):
	"""Kicks/Bans users for flooding"""

	regexs = {}  # Mass highlight
	offenses = {}
	# Users are immune for three secconds to prevent double kicks and bans
	immunities = {}
	repetitionRegex = re.compile(r"(.+?)\1+")


	def inFilter(self, irc, msg):
		if msg.command in ("PRIVMSG", "NOTICE", "JOIN", "PART", "QUIT"):
			channel = msg.args[0]
			if ircutils.isChannel(channel) and\
			   self.registryValue("enabled", channel):
				if msg.command in ("PRIVMSG", "NOTICE"):
					self.checkMessageFlood(irc, msg)
				elif msg.command in ("JOIN", "PART", "QUIT"):
					self.checkJoinFlood(irc, msg)
		return msg


	def generateRecent(self, irc, msg, commands, maxNeeded = 5):
		recent = []
		# Sorted in order of arival
		for item in reversed(irc.state.history):
			if item.command in commands and\
			   item.nick == msg.nick and\
			   item.args[0] == msg.args[0]:
				recent.insert(0, item)
				if len(recent) >= maxNeeded:
					break
		return recent


	def checkJoinFlood(self, irc, msg):
		channel = msg.args[0]
		recentJoins = self.generateRecent(irc, msg, ("JOIN", "PART", "QUIT"), 6)

		# Flaping connection
		if len(recentJoins) >= 6 and\
		   recentJoins[-1].receivedAt - recentJoins[-6].receivedAt < 240:
			self.banForward(irc, msg, "#fix_your_connection")


	def checkMessageFlood(self, irc, msg):
		channel = msg.args[0]
		message = ircutils.stripFormatting(msg.args[1])
		recentMessages = self.generateRecent(irc, msg, ("PRIVMSG", "NOTICE"))

		# Regular message flood
		if len(recentMessages) >= 5:
			if (recentMessages[-1].receivedAt -\
			    recentMessages[-5].receivedAt) <= 6:
				self.floodPunish(irc, msg, "Message", dummy = False)

		# Message repitition flood
		if len(recentMessages) >= 3:
			firstTime = recentMessages[-3].receivedAt
			curTime = recentMessages[-1].receivedAt
			if (recentMessages[-3].args[1] ==\
			    recentMessages[-2].args[1] ==\
			    recentMessages[-1].args[1]) and\
			    curTime - firstTime < 60:
				self.floodPunish(irc, msg, "Message repetition", dummy = False)
				return

		# Repitition
		#def repetitions(r, s):
		#	for match in r.finditer(s):
		#		yield((match.group(1), len(match.group(0)) / len(match.group(1))))

		#repetitionList = list(repetitions(self.repetitionRegex,
		#		recentMessages[-1].args[1]))

		#for rep in repetitionList:
		#	if rep[1] > 10:
		#		self.floodPunish(irc, msg, "Repetition", dummy = True)
		#		return

		# Paste flood
		typedTooFast = lambda recent, old:\
			len(recent.args[1]) > (recent.receivedAt - old.receivedAt) * 30
		if len(recentMessages) >= 4 and\
		   typedTooFast(recentMessages[-1], recentMessages[-2]) and\
		   typedTooFast(recentMessages[-2], recentMessages[-3]) and\
		   typedTooFast(recentMessages[-3], recentMessages[-4]):
			self.floodPunish(irc, msg, "Paste", dummy = False)
			return

		# Slap flood
		isSlap = lambda x: ircmsgs.isAction(x) and x.args[1][8:13] == "slaps"
		if len(recentMessages) > 3 and\
		   isSlap(recentMessages[-1]) and\
		   isSlap(recentMessages[-2]) and\
		   isSlap(recentMessages[-3]) and\
		   (recentMessages[-1].receivedAt - recentMessages[-3].receivedAt) < 30:
			self.floodPunish(irc, msg, "Slap")
			return

		# Mass highlight
		if irc.network in self.regexs and\
		   channel in self.regexs[irc.network]:
			matches = self.regexs[irc.network][channel].findall(message)
			if len(matches) > 10:
				self.floodPunish(irc, msg, "Highlight")
				return

		# CAPS FLOOD
		#def tooManyCaps(s):
		#	if len(s) == 0: return False
		#	numNotCaps = 0
		#	for c in s:
		#		if c in string.ascii_lowercase:
		#			numNotCaps += 1
		#	return numNotCaps / len(s) < 0.25
		#if len(recentMessages) >= 3:
		#	if tooManyCaps(recentMessages[-1].args[1]) and\
		#	   tooManyCaps(recentMessages[-2].args[1]) and\
		#	   tooManyCaps(recentMessages[-3].args[1]):
		#		self.floodPunish(irc, msg, "CAPS", dummy = True)
		#		return


	def banForward(self, irc, msg, channel):
		hostmask = irc.state.nickToHostmask(msg.nick)
		banmaskstyle = conf.supybot.protocols.irc.banmask
		banmask = banmaskstyle.makeBanmask(hostmask)
		irc.queueMsg(ircmsgs.mode(msg.args[0], ("+b", banmask + "$" + channel)))
		self.log.warning("Ban-forwarded %s (%s) from %s to %s.",
				banmask, msg.nick, msg.args[0], channel)


	def floodPunish(self, irc, msg, floodType, dummy = False):
		channel = msg.args[0]

		if (not irc.nick in irc.state.channels[channel].ops) and\
		   (not irc.nick in irc.state.channels[channel].halfops):
			self.log.warning("%s flooded in %s, but not opped.",\
				msg.nick, channel)
			return

		if msg.nick in self.immunities:
			self.log.debug("Not punnishing %s, they are immune.",
				msg.nick)
			return

		if msg.nick in irc.state.channels[channel].ops or\
		   msg.nick in irc.state.channels[channel].halfops or\
		   msg.nick in irc.state.channels[channel].voices:
			self.log.debug("%s flooded in %s. But"\
				+ " I will not punish them because they have"\
				+ " special access.", msg.nick, channel)
			return

		if ircdb.checkCapability(msg.prefix, 'trusted') or\
		   ircdb.checkCapability(msg.prefix, 'admin') or\
		   ircdb.checkCapability(msg.prefix, channel + ',op'):
			self.log.debug("%s flooded in %s. But"\
				+ " I will not punish them because they are"\
				+ " trusted.", msg.nick, channel)
			return

		if msg.host in self.offenses and self.offenses[msg.host] > 2:
			hostmask = irc.state.nickToHostmask(msg.nick)
			banmaskstyle = conf.supybot.protocols.irc.banmask
			banmask = banmaskstyle.makeBanmask(hostmask)
			if not dummy:
				irc.queueMsg(ircmsgs.ban(channel, banmask))
			self.log.warning("Banned %s (%s) from %s for repeated"\
				+ " flooding.", banmask, msg.nick, channel)

		reason = floodType + " flood detected."
		if floodType == "Paste":
			reason += " Use a pastebin like pastebin.ubuntu.com or gist.github.com."

		if not dummy:
			irc.queueMsg(ircmsgs.kick(channel, msg.nick, reason))

		self.log.warning("Kicked %s from %s for %s flooding.",\
				msg.nick, channel, floodType)

		# Don't schedule the same nick twice
		if not (msg.host in self.offenses):
			schedule.addEvent(self.clearOffenses, time.time()+300,
					args=[msg.host])
			self.offenses[msg.host] = 0 # Incremented below
		self.offenses[msg.host] += 1

		self.immunities[msg.nick] = True
		schedule.addEvent(self.unImmunify, time.time()+3,
				args=[msg.nick])

	def clearOffenses(self, host):
		if self.offenses[host] > 1:
			self.offenses[host] -= 1
			schedule.addEvent(self.clearOffenses, time.time()+300,
					args=[host])
		else:
			del self.offenses[host]

	def unImmunify(self, nick):
		del self.immunities[nick]

	def makeRegexp(self, irc, channel):
		if channel is None:
			channels = irc.state.channels.keys()
		else:
			channels = [channel]

		for channelName in channels:
			longNicks = [x for x in\
				irc.state.channels[channelName].users if len(x) > 3]
			s = r"|".join(map(re.escape, longNicks))

			if not irc.network in self.regexs:
				self.regexs[irc.network] = {}

			self.regexs[irc.network][channel] =\
				re.compile(s, re.IGNORECASE)

	def doJoin(self, irc, msg):
		for channel in msg.args[0].split(","):
			self.makeRegexp(irc, channel)

	def doPart(self, irc, msg):
		if msg.nick == irc.nick: return
		for channel in msg.args[0].split(","):
			self.makeRegexp(irc, channel)

	def doQuit(self, irc, msg):
		if msg.nick == irc.nick: return
		self.makeRegexp(irc, None)

	def doKick(self, irc, msg):
		if msg.nick == irc.nick: return
		self.makeRegexp(irc, msg.args[0])

	def doNick(self, irc, msg):
		self.makeRegexp(irc, None)

Class = FloodProtector

