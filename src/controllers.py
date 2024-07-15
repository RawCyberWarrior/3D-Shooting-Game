import hashlib
import math
from random import randint, random, seed, uniform

from . import engine
from . import audio
from . import entities
from . import net
from . import components
from . import net2
from . import particles
from . import ai
from . import constants

from panda3d.core import *

from direct.showbase.DirectObject import DirectObject

types = None
specialTypes = None


def init():
    global types, specialTypes
    # Important: Shield droid and cloak droid MUST come before chaingun droid, due to inheritance issues.
    # When determining the controller's type, readSpawnPacket stops at the
    # first match.
    types = {
        constants.SPAWN_BOT: AIController,
        constants.SPAWN_PLAYER: PlayerController,
        constants.SPAWN_TEAMENTITY: TeamEntityController,
        constants.SPAWN_PHYSICSENTITY: PhysicsEntityController,
        constants.SPAWN_GRENADE: GrenadeController,
        constants.SPAWN_GLASS: GlassController,
        constants.SPAWN_MOLOTOV: MolotovController,
        constants.SPAWN_POD: DropPodController}

    specialTypes = {
        constants.KAMIKAZE_SPECIAL: KamikazeSpecial,
        constants.SHIELD_SPECIAL: ShieldSpecial,
        constants.CLOAK_SPECIAL: CloakSpecial,
        constants.AWESOME_SPECIAL: AwesomeSpecial,
        constants.ROCKET_SPECIAL: RocketSpecial}


class Controller(DirectObject):

    def __init__(self):
        self.criticalPackets = []
        self.entity = None
        self.lastPacketUpdate = engine.clock.time
        self.criticalUpdate = False
        self.active = True

    def addCriticalPacket(self, p, packetUpdate):
        # If we have a critical packet on an update frame, and we add it to the critical packet queue,
        # it will get sent again on the next update frame.
        # So, we don't want that to happen.
        if packetUpdate:
            self.criticalUpdate = True
        elif p not in self.criticalPackets:
            self.criticalPackets.append(p)

    def clearCriticalPackets(self):
        del self.criticalPackets[:]

    def setEntity(self, entity):
        """ObjectEntity calls this function on initialization."""
        assert isinstance(entity, entities.Entity)
        self.entity = entity

    def buildSpawnPacket(self):
        """Builds a packet instructing client(s) to spawn the correct ObjectEntity with the correct ID."""
        p = net.Packet()
        p.add(net.Uint8(constants.PACKET_SPAWN))
        controllerType = 0
        for type in list(types.items()):
            if isinstance(self, type[1]):
                controllerType = type[0]
                break
        p.add(net.Uint8(controllerType))
        p.add(net.Uint32(self.entity.getId()))
        return p

    @staticmethod
    def readSpawnPacket(aiWorld, entityGroup, iterator, entity=None):
        "Static method called by descendants. Assumes entity has already been initialized by the descendant."
        id = net.Uint32.getFrom(iterator)
        entity.setLocal(net.netMode == constants.MODE_SERVER)
        entity.setId(id)
        return entity

    def buildDeletePacket(self, killed=False):
        """Builds a packet instructing clients to delete the Entity."""
        p = net.Packet()
        p.add(net.Uint8(constants.PACKET_DELETE))
        p.add(net.Uint32(self.entity.getId()))
        p.add(net.Boolean(killed))
        return p

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        """Any and all processing / logic goes on in the server update function. The resulting data is packed up in a datagram and broadcast to the clients.
        The base ObjectController.serverUpdate function is meant to be called at the beginning of any derived serverUpdate functions."""

        p = None
        if self.entity is not None and self.entity.active:
            # Header data
            p = net.Packet()
            if packetUpdate:
                self.criticalUpdate = len(self.criticalPackets) > 0
                for packet in self.criticalPackets:
                    p.add(packet)
                del self.criticalPackets[:]
            else:
                self.criticalUpdate = False
            p.add(net.Uint8(constants.PACKET_CONTROLLER))
            p.add(net.Uint8(self.entity.getId()))
        return p

    def needsToSendUpdate(self):
        return self.criticalUpdate

    def clientUpdate(self, aiWorld, entityGroup, iterator=None):
        """The client update function applies the changes calculated by the server update function, even on the server machine.
        The base ObjectController.clientUpdate function is meant to be called at the beginning of any derived clientUpdate functions."""
        if self.entity is not None:
            if iterator is not None:
                self.lastPacketUpdate = engine.clock.time

    def delete(self, killed=False):
        self.ignoreAll()
        self.active = False


class TeamEntityController(Controller):
    """TeamEntityControllers increment their team's money and spawn newly purchased units."""

    def __init__(self):
        Controller.__init__(self)
        self.respawns = []
        self.spawnSound = audio.SoundPlayer("spawn")
        self.lastSpawn = 0
        self.light = engine.Light(color=Vec4(
            0.4, 0.7, 1.0, 1), attenuation=Vec3(0, 0, 0.003))
        self.spawnDelay = 3.0
        self.tutorialMode = False
        self.oldUsername = "Unnamed"
        self.scoreAdditions = 0
        self.moneyAdditions = 0
        self.moneyIncreaseSound = audio.FlatSound(
            "sounds/money.ogg", volume=0.1)

    def buildSpawnPacket(self):
        p = Controller.buildSpawnPacket(self)
        p.add(net2.HighResVec4(self.entity.color))
        if self.entity.dock is not None:
            p.add(net.Uint8(self.entity.dock.teamIndex))
        else:
            p.add(net.Uint8(0))
        p.add(net.Uint8(len(self.entity.allies)))
        for allyId in self.entity.allies:
            p.add(net.Uint8(allyId))
        p.add(net.Int16(self.entity.score))
        p.add(net.Int16(self.entity.matchScore))
        p.add(net.Boolean(self.entity.isSurvivors))
        p.add(net.Boolean(self.entity.isZombies))
        p.add(net.String(self.entity.username))
        p.add(net.Int16(self.entity.money))
        return p

    @staticmethod
    def readSpawnPacket(aiWorld, entityGroup, iterator, entity=None):
        entity = entities.TeamEntity()
        entity = Controller.readSpawnPacket(
            aiWorld, entityGroup, iterator, entity)
        entity.color = net2.HighResVec4.getFrom(iterator)
        dockIndex = net.Uint8.getFrom(iterator)
        if len(aiWorld.docks) > 0:
            entity.dock = [
                x for x in aiWorld.docks if x.teamIndex == dockIndex][0]
        numAllies = net.Uint8.getFrom(iterator)
        for i in range(numAllies):
            entity.addAlly(net.Uint8.getFrom(iterator))
        entity.score = net.Int16.getFrom(iterator)
        entity.matchScore = net.Int16.getFrom(iterator)
        entity.isSurvivors = net.Boolean.getFrom(iterator)
        entity.isZombies = net.Boolean.getFrom(iterator)
        entity.username = net.String.getFrom(iterator)
        entity.money = net.Int16.getFrom(iterator)
        if not entity.isZombies:
            entityGroup.addTeam(entity)
        return entity

    def setEntity(self, entity):
        assert isinstance(entity, entities.TeamEntity)
        Controller.setEntity(self, entity)

    def addScore(self, score):
        self.scoreAdditions += score

    def addMoney(self, money):
        self.moneyAdditions += money

    def clearCriticalPackets(self):
        Controller.clearCriticalPackets(self)
        del self.respawns[:]
        self.scoreAdditions = 0

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        p = Controller.serverUpdate(self, aiWorld, entityGroup, packetUpdate)
        if self.scoreAdditions != 0 or self.moneyAdditions != 0:
            self.addCriticalPacket(p, packetUpdate)
        self.entity.score += self.scoreAdditions
        self.entity.money += self.moneyAdditions
        if self.moneyAdditions > 0 and self.entity.getPlayer() is not None:
            self.moneyIncreaseSound.play()
        self.moneyAdditions = 0
        self.scoreAdditions = 0
        if not self.tutorialMode and self.entity.getPlayer() is None:
            self.entity.score = 0
        p.add(net.Int16(self.entity.score))
        p.add(net.Int16(self.entity.money))
        if self.entity.username != self.oldUsername:
            self.addCriticalPacket(p, packetUpdate)
            p.add(net.Boolean(True))
            p.add(net.String(self.entity.username))
        else:
            p.add(net.Boolean(False))
        self.oldUsername = self.entity.username
        a = [
            x for x in self.respawns if engine.clock.time -
            x[4] > self.spawnDelay]
        p.add(net.Uint8(len(a)))
        for purchase in a:
            isLocalPlayer = purchase[0]
            type = purchase[1]
            special = purchase[2]
            if not self.entity.active:
                return
            if self.entity.isZombies:
                # Zombies spawn at any spawn point other than the first.
                pos = aiWorld.getRandomOpenSpawnPoint(
                    self.entity, entityGroup, zombieSpawnsOnly=True)
            elif self.entity.isSurvivors:
                # Survivors always spawn at the first defined spawn point.
                pos = aiWorld.spawnPoints[0].getPosition()
            else:
                target = None
                player = self.entity.getPlayer()
                if player is not None and player.active:
                    target = player.getPosition()
                elif len(self.entity.actors) > 0:
                    target = self.entity.actors[0].getPosition()
                if target is None:
                    pos = aiWorld.getRandomOpenSpawnPoint(
                        self.entity, entityGroup)
                else:
                    pos = aiWorld.getNearestOpenSpawnPoint(
                        self.entity, entityGroup, target) + Vec3(uniform(-2, 2), uniform(-2, 2), 0)
            if isLocalPlayer:
                isPlatformSpawn = purchase[5] is not None
                if isPlatformSpawn:
                    pos = purchase[5]
                u = entities.PlayerDroid(
                    aiWorld.world,
                    aiWorld.space,
                    controller=PlayerController(),
                    local=True)
                u.setWeapons([self.entity.getPrimaryWeapon(),
                              self.entity.getSecondaryWeapon()])
                u.setSpecial(self.entity.getSpecial())
                u.setUsername(self.entity.getUsername())
                u.controller.setPlatformMode(isPlatformSpawn)
            else:
                u = entities.BasicDroid(
                    aiWorld.world,
                    aiWorld.space,
                    controller=AIController(),
                    local=net.netMode == constants.MODE_SERVER)
                u.setWeapons([type])
                u.setSpecial(special)
                u.teamIndex = purchase[3]
                self.entity.actors.append(u)
            pos.setZ(pos.getZ() + u.radius)
            u.setPosition(pos)
            u.setTeamId(self.entity.getId())
            u.commitChanges()
            p.add(net2.HighResVec3(Vec3(pos)))
            self.addCriticalPacket(p, packetUpdate)
            entityGroup.spawnEntity(u)
            self.respawns.remove(purchase)
        return p

    def clientUpdate(self, aiWorld, entityGroup, data=None):
        Controller.clientUpdate(self, aiWorld, entityGroup, data)
        if data is not None:
            self.entity.score = net.Int16.getFrom(data)
            self.entity.money = net.Int16.getFrom(data)
            if net.Boolean.getFrom(data):
                self.entity.username = net.String.getFrom(data)
            numPurchases = net.Uint8.getFrom(data)
            for i in range(numPurchases):
                pos = net2.HighResVec3.getFrom(data)
                self.spawnSound.play(position=pos)
                self.light.setPos(pos)
                self.light.add()
                self.lastSpawn = engine.clock.time
        if engine.clock.time - self.lastSpawn > 4.0:
            self.light.remove()
        else:
            self.light.setAttenuation(
                (0,
                 0,
                 0.001 +
                 math.pow(
                     engine.clock.time -
                     self.lastSpawn,
                     2) *
                    0.005))

    def respawn(self, weapon, special, teamIndex):
        if weapon is not None and (len(
                [x for x in self.respawns if x[0] == False and x[3] == teamIndex]) == 0 or self.entity.isZombies):
            self.respawns.append(
                (False, weapon, special, teamIndex, engine.clock.time))

    def respawnPlayer(self, primary, secondary, special):
        if len([x for x in self.respawns if x[0]]) == 0:
            # None means we are not spawning the player on a platform
            self.respawns.append(
                (True, primary, secondary, special, engine.clock.time, None))

    def platformSpawnPlayer(self, primary, secondary, special, pos):
        # pos is the position to spawn the player at
        self.respawns.append(
            (True,
             primary,
             secondary,
             special,
             engine.clock.time -
             self.spawnDelay,
             pos))


class ObjectController(Controller):

    def __init__(self):
        Controller.__init__(self)
        self.isStatic = False
        self.newPositionData = False
        self.snapshots = []
        self.lastSentSnapshot = net2.EntitySnapshot()
        self.lastSnapshot = net2.EntitySnapshot()
        self.upperHeightLimit = 70
        self.lowerHeightLimit = -30

    def setEntity(self, entity):
        """ObjectEntity calls this function on initialization."""
        assert isinstance(entity, entities.ObjectEntity)
        Controller.setEntity(self, entity)

    def buildSpawnPacket(self, isPhysicsEntity=False):
        """Builds a packet instructing client(s) to spawn the correct ObjectEntity with the correct ID."""
        p = Controller.buildSpawnPacket(self)
        self.entity.commitChanges()
        if isPhysicsEntity:
            p.add(net.String(self.entity.directory))
            p.add(net.String(self.entity.dataFile))
        p.add(net2.HighResVec3(self.entity.getPosition()))
        p.add(net2.StandardVec3(self.entity.getLinearVelocity()))
        p.add(net2.StandardVec3(self.entity.getRotation()))
        return p

    @staticmethod
    def readSpawnPacket(
            aiWorld,
            entityGroup,
            iterator,
            entity=None,
            isPhysicsEntity=False):
        "Static method called by descendants. Assumes entity has already been initialized by the descendant."
        entity = Controller.readSpawnPacket(
            aiWorld, entityGroup, iterator, entity)
        if isPhysicsEntity:
            directory = net.String.getFrom(iterator)
            dataFile = net.String.getFrom(iterator)
            entity.loadDataFile(
                aiWorld.world,
                aiWorld.space,
                engine.readPhysicsEntityFile(
                    dataFile + ".txt"),
                directory,
                dataFile)
        pos = net2.HighResVec3.getFrom(iterator)
        vel = net2.StandardVec3.getFrom(iterator)
        rot = net2.StandardVec3.getFrom(iterator)
        entity.setPosition(pos)
        entity.setRotation(Vec3(rot.getX(), rot.getY(), rot.getZ()))
        entity.setLinearVelocity(vel)
        entity.commitChanges()
        entity.controller.commitLastPosition()
        return entity

    def commitLastPosition(self):
        snapshot = net2.EntitySnapshot()
        snapshot.takeSnapshot(self.entity)
        self.snapshots = [snapshot]
        self.lastSentSnapshot = self.snapshots[0]

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        """Any and all processing / logic goes on in the server update function. The resulting data is packed up in a datagram and broadcast to the clients.
        The base ObjectController.serverUpdate function is meant to be called at the beginning of any derived serverUpdate functions."""

        p = Controller.serverUpdate(self, aiWorld, entityGroup, packetUpdate)
        if self.entity is not None and self.entity.active:
            # Physics data
            self.entity.commitChanges()
            snapshot = net2.EntitySnapshot()
            snapshot.takeSnapshot(self.entity)
            if not packetUpdate or self.isStatic or (self.lastSentSnapshot.almostEquals(
                    snapshot) and self.entity.body.getLinearVel().length() < 0.5):
                p.add(net.Boolean(False))
                self.newPositionData = False
            else:
                self.newPositionData = True
                p.add(net.Boolean(True))
                self.lastSnapshot = snapshot
                p.add(snapshot)
            z = self.entity.getPosition().getZ()
            if z < self.lowerHeightLimit or z > self.upperHeightLimit:
                self.entity.killer = None
                self.entity.kill(aiWorld, entityGroup)
        return p

    def needsToSendUpdate(self):
        if self.newPositionData or Controller.needsToSendUpdate(self):
            self.lastSentSnapshot = self.lastSnapshot
            return True
        else:
            return False

    def clientUpdate(self, aiWorld, entityGroup, iterator=None):
        """The client update function applies the changes calculated by the server update function, even on the server machine.
        The base ObjectController.clientUpdate function is meant to be called at the beginning of any derived clientUpdate functions."""
        Controller.clientUpdate(self, aiWorld, entityGroup, iterator)
        if self.entity is not None:
            currentTime = engine.clock.time - 0.1
            if len(self.snapshots) == 0:
                self.snapshots.append(net2.EntitySnapshot())
                self.snapshots[0].takeSnapshot(self.entity)
            if iterator is not None:
                if net.Boolean.getFrom(iterator):
                    snapshot = net2.EntitySnapshot.getFrom(iterator)
                else:
                    snapshot = net2.EntitySnapshot()
                    snapshot.setFrom(self.snapshots[0])
                self.snapshots.insert(0, snapshot)
                self.snapshots = self.snapshots[:6]
            elif not self.entity.isLocal and len([x for x in self.snapshots if x.time > currentTime]) == 0:
                snapshot = net2.EntitySnapshot()
                snapshot.setFrom(self.snapshots[0])
                self.snapshots.insert(0, snapshot)
                self.snapshots = self.snapshots[:6]

            if not self.entity.isLocal:
                a = 0
                b = 0
                numSnapshots = len(self.snapshots)
                for i in range(numSnapshots):
                    if self.snapshots[i].time > currentTime and numSnapshots > i + \
                            1 and self.snapshots[i + 1].time < currentTime:
                        a = i + 1
                        b = i
                        break
                if self.snapshots[b].time > self.snapshots[a].time:
                    self.snapshots[a].lerp(self.snapshots[b], min(1.0, (currentTime - self.snapshots[a].time) / (
                        self.snapshots[b].time - self.snapshots[a].time))).commitTo(self.entity)
                self.entity.commitChanges()

    def delete(self, killed=False):
        Controller.delete(self, killed)


class FragmentController(ObjectController):

    def __init__(self, velocity):
        ObjectController.__init__(self)
        self.velocity = Vec3(velocity)
        self.spawnTime = engine.clock.time
        self.lifeTime = 3 + uniform(0, 2)
        self.justSpawned = True

    def setEntity(self, entity):
        assert isinstance(entity, entities.Fragment)
        ObjectController.setEntity(self, entity)

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        # Fragments are always processed on client
        self.entity.commitChanges()

        if engine.clock.time > self.spawnTime + \
                self.lifeTime or self.entity.getPosition().getZ() < -30:
            self.entity.delete(entityGroup)
            return None

        if self.justSpawned:
            self.entity.setLinearVelocity(self.velocity)
            self.justSpawned = False
        return None

    def clientUpdate(self, aiWorld, entityGroup, data=None):
        pass


class GlassController(Controller):

    def __init__(self):
        Controller.__init__(self)

    def setEntity(self, entity):
        assert isinstance(entity, entities.Glass)
        Controller.setEntity(self, entity)

    def buildSpawnPacket(self):
        p = Controller.buildSpawnPacket(self)
        p.add(net2.StandardVec3(self.entity.getPosition()))
        p.add(net2.StandardVec3(self.entity.getRotation()))
        p.add(net.StandardFloat(self.entity.glassWidth))
        p.add(net.StandardFloat(self.entity.glassHeight))
        return p

    @staticmethod
    def readSpawnPacket(aiWorld, entityGroup, iterator, entity=None):
        entity = entities.Glass(aiWorld.world, aiWorld.space)
        entity = Controller.readSpawnPacket(
            aiWorld, entityGroup, iterator, entity)
        pos = net2.StandardVec3.getFrom(iterator)
        hpr = net2.StandardVec3.getFrom(iterator)
        entity.initGlass(
            aiWorld.world,
            aiWorld.space,
            net.StandardFloat.getFrom(iterator),
            net.StandardFloat.getFrom(iterator))
        entity.setPosition(pos)
        entity.setRotation(Vec3(hpr.getX(), hpr.getY(), hpr.getZ()))
        return entity

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        # Glass panes don't generally move. They just shatter.
        return None

    def clientUpdate(self, aiWorld, entityGroup, data=None):
        if self.entity.shattered:
            self.entity.kill(aiWorld, entityGroup)
            return


class PhysicsEntityController(ObjectController):
    """Controls physics objects."""

    @staticmethod
    def readSpawnPacket(aiWorld, entityGroup, iterator, entity=None):
        entity = entities.PhysicsEntity(aiWorld.world, aiWorld.space)
        entity = ObjectController.readSpawnPacket(
            aiWorld, entityGroup, iterator, entity, isPhysicsEntity=True)
        return entity

    def buildSpawnPacket(self):
        p = ObjectController.buildSpawnPacket(self, isPhysicsEntity=True)
        return p


class DropPodController(ObjectController):

    def __init__(self):
        ObjectController.__init__(self)
        self.inAirTime = 2.0
        self.landed = False
        self.landingSound = audio.SoundPlayer("pod-landing")
        self.particleGroup = None
        self.finalPosition = None
        self.startPosition = None
        self.lastPayout = 0
        self.payoutAmount = 20
        self.payoutDelay = 1.5
        self.captureDistance = 20
        self.money = 300
        self.warningSound = audio.SoundPlayer("kamikaze-special")
        self.warningTime = -1
        self.entrySound = audio.FlatSound("sounds/pod-entry.ogg", volume=0.5)
        self.entrySoundPlayed = False
        self.upperHeightLimit = 1000

    def setFinalPosition(self, pos):
        pivot = Vec3(0, 0, 50)
        self.finalPosition = pos + Vec3(0, 0, self.entity.vradius)
        dir = (pivot * 2.0) - self.finalPosition
        dir.normalize()
        self.startPosition = pivot + (dir * 500)
        self.entity.setPosition(self.startPosition)
        self.entity.node.lookAt(Point3(self.finalPosition))

    def setEntity(self, entity):
        """Entity calls this function on initialization."""
        assert isinstance(entity, entities.DropPod)
        ObjectController.setEntity(self, entity)

    def buildSpawnPacket(self, isPhysicsEntity=False):
        """Builds a packet instructing client(s) to spawn the correct Entity with the correct ID."""
        p = ObjectController.buildSpawnPacket(self)
        p.add(net2.HighResVec3(self.finalPosition))
        p.add(net.StandardFloat(engine.clock.time - self.entity.spawnTime))
        p.add(net.Uint16(self.money))
        return p

    @staticmethod
    def readSpawnPacket(
            aiWorld,
            entityGroup,
            iterator,
            entity=None,
            isPhysicsEntity=False):
        "Static method called by descendants. Assumes entity has already been initialized by the descendant."
        entity = entities.DropPod(aiWorld.world, aiWorld.space, False)
        entity = ObjectController.readSpawnPacket(
            aiWorld, entityGroup, iterator, entity)
        entity.controller.setFinalPosition(net2.HighResVec3.getFrom(iterator))
        entity.spawnTime = engine.clock.time - \
            net.StandardFloat.getFrom(iterator)
        entity.controller.money = net.Uint16.getFrom(iterator)
        return entity

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        if not self.landed:
            aliveTime = engine.clock.time - self.entity.spawnTime
            self.entity.setPosition(self.startPosition +
                                    (self.finalPosition -
                                     self.startPosition) *
                                    min(1, (aliveTime /
                                            self.inAirTime)))
        p = ObjectController.serverUpdate(
            self, aiWorld, entityGroup, packetUpdate)
        paid = False
        if self.landed and engine.clock.time - \
                self.lastPayout > self.payoutDelay and self.warningTime == -1:
            droid = aiWorld.getNearestDroid(
                entityGroup, self.entity.getPosition())
            if droid is not None and (
                    droid.getPosition() -
                    self.entity.getPosition()).length() < self.captureDistance:
                p.add(net.Boolean(True))
                p.add(net.Uint8(droid.getTeam().getId()))
                paid = True
                self.money -= self.payoutAmount
                self.lastPayout = engine.clock.time
                self.addCriticalPacket(p, packetUpdate)
        if not paid:
            p.add(net.Boolean(False))
        p.add(net.Uint16(max(self.money, 0)))
        if self.warningTime != -1 and engine.clock.time - self.warningTime > 3.0:
            self.entity.killer = None
            self.entity.kill(aiWorld, entityGroup)
        return p

    def clientUpdate(self, aiWorld, entityGroup, data=None):
        ObjectController.clientUpdate(self, aiWorld, entityGroup, data)
        if data is not None:
            if net.Boolean.getFrom(data):  # Pay money to some team or other
                team = entityGroup.getEntity(net.Uint8.getFrom(data))
                if team is not None:
                    team.controller.addMoney(self.payoutAmount)
            self.money = net.Uint16.getFrom(data)
        self.entity.amountIndicator.setText("$" + str(self.money))
        if base.camera is not None:
            self.entity.amountIndicatorNode.setScale(
                (self.entity.getPosition() - base.camera.getPos()).length() * 0.04)
        if not self.landed:
            if not self.entrySoundPlayed:
                self.entrySound.play()
                self.entrySoundPlayed = True
            if self.particleGroup is None:
                self.particleGroup = particles.SmokeParticleGroup(
                    self.entity.getPosition())
                particles.add(self.particleGroup)
            self.particleGroup.setPosition(self.entity.getPosition())
            aliveTime = engine.clock.time - self.entity.spawnTime
            if aliveTime >= self.inAirTime and not self.landed:
                self.landed = True
                self.landingSound.play(position=self.entity.getPosition())
                self.entity.setLinearVelocity(Vec3(0, 0, 0))
        else:
            if self.money <= 0 and self.warningTime == -1:
                self.warningTime = engine.clock.time
                self.warningSound.play(entity=self.entity)

    def delete(self, killed=False):
        ObjectController.delete(self, killed)
        if self.particleGroup is not None:
            self.particleGroup.delete()


class GrenadeController(ObjectController):
    """GrenadeController handles particles, and also trigger the detonation (unless the grenade is triggered by being damaged)."""

    def __init__(self):
        ObjectController.__init__(self)
        self.bounceTime = -1
        self.bounceSound = audio.SoundPlayer("grenade-bounce")
        self.lastPosition = None
        self.particleGroup = None
        self.light = engine.Light(color=Vec4(
            1.0, 0.7, 0.4, 1), attenuation=Vec3(0, 0, 0.01))
        self.light.add()

    def buildSpawnPacket(self):
        p = ObjectController.buildSpawnPacket(self)
        p.add(net.Uint8(self.entity.getTeam().getId()))
        return p

    @staticmethod
    def readSpawnPacket(aiWorld, entityGroup, iterator, entity=None):
        entity = entities.Grenade(aiWorld.world, aiWorld.space)
        entity = ObjectController.readSpawnPacket(
            aiWorld, entityGroup, iterator, entity)
        entity.setTeamId(net.Uint8.getFrom(iterator))
        return entity

    def setEntity(self, entity):
        assert isinstance(entity, entities.Grenade)
        ObjectController.setEntity(self, entity)

    def trigger(self):
        "Starts the (short) fuse to explode the grenade."
        if self.bounceTime == -1 and engine.clock.time > self.entity.spawnTime + 0.5:
            self.bounceTime = engine.clock.time
            self.bounceSound.play(position=self.entity.getPosition())

    def clientUpdate(self, aiWorld, entityGroup, data=None):
        ObjectController.clientUpdate(self, aiWorld, entityGroup, data)
        pos = self.entity.getPosition()
        self.light.setPos(pos)
        if self.particleGroup is None:
            self.particleGroup = particles.SmokeParticleGroup(pos)
            particles.add(self.particleGroup)
        self.particleGroup.setPosition(pos)

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        pos = self.entity.getPosition()
        if self.lastPosition is None:
            self.lastPosition = pos
        else:
            # Check to make sure the grenade didn't go through a wall
            vector = self.entity.getPosition() - self.lastPosition
            distance = vector.length()
            if distance > 0:
                vector.normalize()
                queue = aiWorld.getCollisionQueue(
                    self.lastPosition, vector, engine.renderEnvironment)
                for i in range(queue.getNumEntries()):
                    entry = queue.getEntry(i)
                    collision = entry.getSurfacePoint(render)
                    v = collision - self.lastPosition
                    if v.length() < distance:
                        self.entity.setPosition(
                            collision - (vector * self.entity.radius))
                        self.entity.commitChanges()
                        self.trigger()
                        break

        self.lastPosition = self.entity.getPosition()

        p = ObjectController.serverUpdate(
            self, aiWorld, entityGroup, packetUpdate)

        enemy = aiWorld.getNearestEnemy(
            entityGroup, self.entity.getPosition(), self.entity.getTeam())
        if enemy is not None and Vec3(enemy.getPosition(
        ) - self.entity.getPosition()).length() < enemy.radius + self.entity.radius:
            self.entity.kill(aiWorld, entityGroup)

        if self.bounceTime == -1:
            if aiWorld.testCollisions(
                    self.entity.collisionNodePath).getNumEntries() > 0:
                self.trigger()
        if (self.bounceTime != -
            1 and engine.clock.time > self.bounceTime +
            0.6) or (engine.clock.time > self.entity.spawnTime +
                     5) or not self.entity.grenadeAlive:
            self.entity.kill(aiWorld, entityGroup)
        return p

    def delete(self, killed=False):
        self.light.remove()
        ObjectController.delete(self, killed)


class MolotovController(ObjectController):
    """MolotovController handles particles and fire damage."""

    def __init__(self):
        ObjectController.__init__(self)
        self.lastPosition = None
        self.particleGroup = None
        self.light = engine.Light(color=Vec4(
            1.0, 0.6, 0.2, 1), attenuation=Vec3(0, 0, 0.005))
        self.light.add()
        self.finalPos = None
        self.lifeTime = 6.0

    def buildSpawnPacket(self):
        p = ObjectController.buildSpawnPacket(self)
        p.add(net.Uint8(self.entity.actor.getId()))
        p.add(net.Uint8(self.entity.getTeam().getId()))
        return p

    @staticmethod
    def readSpawnPacket(aiWorld, entityGroup, iterator, entity=None):
        entity = entities.Molotov(aiWorld.world, aiWorld.space)
        entity = ObjectController.readSpawnPacket(
            aiWorld, entityGroup, iterator, entity)
        entity.setActor(entityGroup.getEntity(net.Uint8.getFrom(iterator)))
        entity.setTeamId(net.Uint8.getFrom(iterator))
        return entity

    def setEntity(self, entity):
        assert isinstance(entity, entities.Molotov)
        ObjectController.setEntity(self, entity)

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        pos = self.entity.getPosition()
        if self.lastPosition is None:
            self.lastPosition = pos
        else:
            # Check to make sure the grenade didn't go through a wall
            vector = self.entity.getPosition() - self.lastPosition
            distance = vector.length()
            if distance > 0:
                vector.normalize()
                queue = aiWorld.getCollisionQueue(
                    self.lastPosition, vector, engine.renderEnvironment)
                for i in range(queue.getNumEntries()):
                    entry = queue.getEntry(i)
                    collision = entry.getSurfacePoint(render)
                    v = collision - self.lastPosition
                    if v.length() < distance:
                        self.entity.setPosition(
                            collision - (vector * self.entity.radius))
                        self.entity.commitChanges()
                        break

        self.lastPosition = self.entity.getPosition()

        p = ObjectController.serverUpdate(
            self, aiWorld, entityGroup, packetUpdate)

        if engine.clock.time - self.entity.spawnTime > self.lifeTime:
            self.entity.delete(entityGroup)

        return p

    def clientUpdate(self, aiWorld, entityGroup, data=None):
        ObjectController.clientUpdate(self, aiWorld, entityGroup, data)
        pos = self.entity.getPosition()
        self.light.setPos(pos)
        if self.particleGroup is None:
            self.particleGroup = particles.FireParticleGroup(pos)
            self.particleGroup.isIndependent = True
            particles.add(self.particleGroup)
        self.particleGroup.setPosition(pos)
        for enemy in (
            x for x in list(entityGroup.entities.values()) if isinstance(
                x, entities.Actor) and not x.getTeam().isAlly(
                self.entity.getTeam()) and (
                x.getPosition() - self.entity.getPosition()).length() < 8.0):
            enemy.controller.setOnFire(self.entity.actor)

    def delete(self, killed=False):
        self.light.remove()
        ObjectController.delete(self, killed)


class ActorController(ObjectController):

    def __init__(self):
        ObjectController.__init__(self)
        self.healthAddition = 0
        self.lastHealthAddition = 0
        self.componentsNeedUpdate = False

    def setEntity(self, entity):
        assert isinstance(entity, entities.Actor)
        ObjectController.setEntity(self, entity)

    def needsToSendUpdate(self):
        return ObjectController.needsToSendUpdate(
            self) or self.componentsNeedUpdate or self.lastHealthAddition != 0

    def buildSpawnPacket(self):
        p = ObjectController.buildSpawnPacket(self)
        p.add(net.Uint8(self.entity.getTeam().getId()))
        return p

    @staticmethod
    def readSpawnPacket(aiWorld, entityGroup, iterator, entity=None):
        entity = ObjectController.readSpawnPacket(
            aiWorld, entityGroup, iterator, entity)
        entity.setTeamId(net.Uint8.getFrom(iterator))
        if not isinstance(entity, entities.PlayerDroid):
            entity.getTeam().actors.append(entity)
        return entity

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        p = ObjectController.serverUpdate(
            self, aiWorld, entityGroup, packetUpdate)
        self.componentsNeedUpdate = False
        for component in self.entity.components:
            p2 = component.serverUpdate(aiWorld, entityGroup, packetUpdate)
            if packetUpdate:
                needUpdate = component.needsToSendUpdate()
                self.newPositionData = self.newPositionData or needUpdate
                if needUpdate:
                    self.componentsNeedUpdate = True
                    p.add(p2)
        p.add(net.Uint8(255))  # End of component packets
        p.add(net.Boolean(self.onFire))
        if self.entity.health < self.entity.maxHealth and (
            engine.clock.time -
            self.lastDamage > 4.0 or (
                self.entity.getTeam().dock is not None and (
                    self.entity.getTeam().dock.getPosition() -
                self.entity.getPosition()).length() < self.entity.getTeam().dock.radius)):
            self.healthAddition += 60 * engine.clock.timeStep
        self.entity.health += int(self.healthAddition)
        self.lastHealthAddition = self.healthAddition
        self.healthAddition = 0
        p.add(net.Int16(self.entity.health))
        if self.entity.health <= 0:
            self.entity.kill(aiWorld, entityGroup, True)
        return p

    def actorDamaged(self, entity, damage, ranged):
        self.healthAddition -= int(damage)

    def clientUpdate(self, aiWorld, entityGroup, data=None):
        ObjectController.clientUpdate(self, aiWorld, entityGroup, data)
        if data is not None:
            id = net.Uint8.getFrom(data)
            updatedComponents = []
            while id != 255:
                self.entity.components[id].clientUpdate(
                    aiWorld, entityGroup, data)
                updatedComponents.append(id)
                id = net.Uint8.getFrom(data)
            for id in (x for x in range(len(self.entity.components))
                       if x not in updatedComponents):
                self.entity.components[id].clientUpdate(aiWorld, entityGroup)

            self.onFire = net.Boolean.getFrom(data)
            self.entity.health = net.Int16.getFrom(data)
        else:
            for component in self.entity.components:
                component.clientUpdate(aiWorld, entityGroup)

    def delete(self, killed=False):
        ObjectController.delete(self, killed)


class DroidController(ActorController):

    def __init__(self):
        ActorController.__init__(self)
        self.activeWeapon = 0
        self.lastActiveWeapon = -1
        self.targetPos = Vec3(0, 0, 0)
        self.torque = 300
        self.maxSpeed = 1
        self.lastDamage = 0
        self.alarmSound = audio.SoundPlayer("alarm")
        self.lastSentTargetPos = Vec3()
        self.targetedEnemy = None
        self.lastTargetedEnemy = None
        self.lastPosition = None
        self.onFire = False
        self.fireTimer = -1
        self.lastFireDamage = -1
        self.fireEntity = None
        self.fireParticles = None
        self.clipCheckCount = 0

    def buildSpawnPacket(self):
        p = ActorController.buildSpawnPacket(self)
        p.add(net.Uint8(len(self.entity.weaponIds)))
        for id in self.entity.weaponIds:
            if id is None:  # 255 = None
                p.add(net.Uint8(255))
            else:
                p.add(net.Uint8(id))
        p.add(net.Uint8(255 if self.entity.specialId ==
                        None else self.entity.specialId))
        p.add(net.Uint8(self.activeWeapon))
        return p

    @staticmethod
    def readSpawnPacket(aiWorld, entityGroup, iterator, entity=None):
        entity = ActorController.readSpawnPacket(
            aiWorld, entityGroup, iterator, entity)
        numWeapons = net.Uint8.getFrom(iterator)
        weapons = []
        for _ in range(numWeapons):
            id = net.Uint8.getFrom(iterator)
            if id == 255:  # 255 = None
                id = None
            weapons.append(id)
        entity.setWeapons(weapons)
        specialId = net.Uint8.getFrom(iterator)
        if specialId == 255:
            specialId = None
        entity.setSpecial(specialId)
        entity.controller.activeWeapon = net.Uint8.getFrom(iterator)
        entity.components[entity.controller.activeWeapon].show()
        return entity

    def reload(self):
        weapon = self.entity.components[self.activeWeapon]
        if isinstance(weapon, components.Gun):
            weapon.reload()

    def isReloading(self):
        weapon = self.entity.components[self.activeWeapon]
        return isinstance(weapon, components.Gun) and weapon.reloadActive

    def enableSpecial(self):
        self.entity.special.enable()

    def setOnFire(self, entity):
        self.onFire = True
        self.fireTimer = engine.clock.time
        self.fireEntity = entity

    def setEntity(self, entity):
        assert isinstance(entity, entities.BasicDroid)
        ActorController.setEntity(self, entity)

    def needsToSendUpdate(self):
        if (self.targetPos - self.lastSentTargetPos).length(
        ) > 0.2 or ActorController.needsToSendUpdate(self):
            self.lastSentTargetPos = Vec3(self.targetPos)
            return True
        else:
            return False

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        if self.entity.pinned:
            if engine.clock.time - self.entity.pinTime > 5.0:
                self.entity.pinned = False
                self.entity.pinPosition = None
                self.entity.pinRotation = None
            else:
                self.entity.setPosition(self.entity.pinPosition)
                self.entity.setRotation(self.entity.pinRotation)
                self.entity.setLinearVelocity(Vec3(0, 0, 0))

        if self.entity.special is not None:
            specialPacket = self.entity.special.serverUpdate(
                aiWorld, entityGroup, packetUpdate)

        pos = self.entity.getPosition()
        if self.lastPosition is None:
            self.lastPosition = pos
        else:
            clipped = False
            if self.clipCheckCount < 10:
                # Check to make sure we didn't go through a wall
                vector = self.entity.getPosition() - self.lastPosition
                distance = vector.length()
                if distance > self.entity.radius * 0.9:
                    vector.normalize()
                    queue = aiWorld.getCollisionQueue(
                        self.lastPosition, vector, engine.renderEnvironment)
                    for i in range(queue.getNumEntries()):
                        entry = queue.getEntry(i)
                        collision = entry.getSurfacePoint(render)
                        v = collision - self.lastPosition
                        if v.length() < distance:
                            clipped = True
                            self.entity.setPosition(
                                collision - (vector * self.entity.radius))
                            self.entity.commitChanges()
                            break
            if clipped:
                self.clipCheckCount += 1
            else:
                # We didn't clip this time, so reset the count.
                self.clipCheckCount = 0

        self.lastPosition = self.entity.getPosition()

        if self.onFire:
            if engine.clock.time - self.fireTimer > 2.0:
                self.onFire = False
                self.fireEntity = None
                self.fireTimer = -1
            elif engine.clock.time - self.lastFireDamage > 0.5:
                self.lastFireDamage = engine.clock.time
                self.entity.damage(self.fireEntity, 8, ranged=False)

        p = ActorController.serverUpdate(
            self, aiWorld, entityGroup, packetUpdate)

        p.add(net.Boolean(self.onFire))

        if self.activeWeapon != self.lastActiveWeapon:
            p.add(net.Boolean(True))
            p.add(net.Uint8(self.activeWeapon))
            self.addCriticalPacket(p, packetUpdate)
        else:
            p.add(net.Boolean(False))
        p.add(net2.LowResVec3(self.targetPos))
        if self.entity.special is not None:
            p.add(specialPacket)
        return p

    def actorDamaged(self, entity, damage, ranged):
        ActorController.actorDamaged(self, entity, damage, ranged)
        self.lastDamage = engine.clock.time
        if self.entity.pinned:
            self.lastPosition = self.entity.getPosition()

    def clientUpdate(self, aiWorld, entityGroup, iterator=None):
        ActorController.clientUpdate(self, aiWorld, entityGroup, iterator)
        if iterator is not None:
            self.onFire = net.Boolean.getFrom(iterator)  # We're on fire
            if net.Boolean.getFrom(iterator):
                if self.lastActiveWeapon != -1:
                    self.entity.components[self.lastActiveWeapon].hide()
                self.activeWeapon = net.Uint8.getFrom(iterator)
                self.entity.components[self.activeWeapon].show()
                self.lastActiveWeapon = self.activeWeapon
            self.targetPos = net2.LowResVec3.getFrom(iterator)

        if self.entity.health <= self.entity.maxHealth * 0.15:
            if not self.alarmSound.isPlaying():
                self.alarmSound.play(entity=self.entity)
        else:
            self.alarmSound.stop()

        if self.onFire:
            if self.fireParticles is None:
                self.fireParticles = particles.FireParticleGroup(
                    self.entity.getPosition())
                particles.add(self.fireParticles)
            self.fireParticles.setPosition(self.entity.getPosition())

        if self.entity.components[self.activeWeapon].reloadActive:
            self.entity.crosshairNode.show()
            self.entity.crosshairNode.setR(engine.clock.time * 30)
        else:
            self.entity.crosshairNode.hide()

        if engine.clock.time - self.entity.spawnTime < 4.0:
            self.entity.setShielded(True)
            self.entity.initialSpawnShieldEnabled = True
        elif self.entity.initialSpawnShieldEnabled:
            self.entity.setShielded(False)
            self.entity.initialSpawnShieldEnabled = False
        if self.entity.special is not None:
            self.entity.special.clientUpdateStart(
                aiWorld, entityGroup, iterator)

    def delete(self, killed=False):
        ActorController.delete(self, killed)
        self.alarmSound.delete()
        if self.fireParticles is not None:
            self.fireParticles.delete()
        if self.entity.special is not None:
            self.entity.special.delete()


class PlayerController(DroidController):
    """The PlayerController handles all user input when active. Don't have more than one of these at a time."""

    def __init__(self):
        DroidController.__init__(self)
        self.keyMap = {
            "left": False,
            "right": False,
            "forward": False,
            "down": False,
            "jump": False,
            "switch-weapon": False,
            "fire": False,
            "alternate-action": False,
            "melee": False,
            "reload": False,
            "sprint": False}
        self.activeWeapon = 1
        self.angleX = 0
        self.angleY = math.radians(-90)
        self.inputEnabled = True
        self.targetPos = Vec3(0, 0, 0)
        self.lastJump = 0
        self.lastCommandTimes = [0, 0]
        self.commands = []
        self.isPlatformMode = False
        self.zoomed = False
        self.defaultFov = engine.defaultFov
        self.fov = self.defaultFov
        self.desiredFov = self.defaultFov
        self.currentFov = self.defaultFov
        self.defaultCameraOffset = Vec3(-1.5, -8, 2.25)
        self.cameraOffset = Vec3(self.defaultCameraOffset)
        self.desiredCameraOffset = Vec3(self.defaultCameraOffset)
        self.currentCameraOffset = Vec3(self.defaultCameraOffset)
        self.defaultMouseSpeed = 1.0
        self.zoomTime = -1
        self.totalZoomTime = 0.12
        self.currentCrosshair = -1  # Used by GameUI to display the correct cursor
        self.sprinting = False
        self.lastSentSprinting = False
        self.targetDistance = 0
        self.lastTargetCheck = 0

    def needsToSendUpdate(self):
        if DroidController.needsToSendUpdate(
                self) or self.lastSentSprinting != self.sprinting:
            self.lastSentSprinting = self.sprinting
            return True
        else:
            return False

    def buildSpawnPacket(self):
        p = DroidController.buildSpawnPacket(self)
        p.add(net.String(self.entity.username))
        engine.log.debug("Building spawn packet for local player " +
                         self.entity.username + " - ID: " + str(self.entity.getId()))
        return p

    @staticmethod
    def readSpawnPacket(aiWorld, entityGroup, iterator, entity=None):
        entity = entities.PlayerDroid(
            aiWorld.world, aiWorld.space, PlayerController(), local=False)
        entity = DroidController.readSpawnPacket(
            aiWorld, entityGroup, iterator, entity)
        entity.getTeam().setPlayer(entity)
        entity.setUsername(net.String.getFrom(iterator))
        engine.log.debug("Spawning remote player " +
                         entity.username + " - ID: " + str(entity.getId()))
        return entity

    def setEntity(self, entity):
        assert isinstance(entity, entities.PlayerDroid)
        DroidController.setEntity(self, entity)
        if entity.isLocal:
            self.mouse = engine.Mouse()
            self.pickRayNode = CollisionNode("pickRayNode")
            self.pickRayNP = camera.attachNewNode(self.pickRayNode)
            self.pickRay = CollisionRay()
            self.pickRayNode.setIntoCollideMask(BitMask32(0))
            self.pickRayNode.setFromCollideMask(BitMask32(1))
            self.pickRayNode.addSolid(self.pickRay)
            self.accept("a", self.setKey, ["left", True])
            self.accept("d", self.setKey, ["right", True])
            self.accept("w", self.setKey, ["forward", True])
            self.accept("s", self.setKey, ["down", True])
            self.accept("a-up", self.setKey, ["left", False])
            self.accept("d-up", self.setKey, ["right", False])
            self.accept("w-up", self.setKey, ["forward", False])
            self.accept("s-up", self.setKey, ["down", False])
            self.accept("space", self.setKey, ["jump", True])
            self.accept("space-up", self.setKey, ["jump", False])
            self.accept("tab", self.setKey, ["switch-weapon", True])
            self.accept("tab-up", self.setKey, ["switch-weapon", False])
            self.accept("mouse1", self.setKey, ["fire", True])
            self.accept("mouse1-up", self.setKey, ["fire", False])
            self.accept("mouse2", self.setKey, ["alternate-action", True])
            self.accept("mouse2-up", self.setKey, ["alternate-action", False])
            self.accept("mouse3", self.toggleZoom)
            self.accept("shift", self.sprint)
            self.accept("shift-up", self.setKey, ["sprint", False])
            self.accept("f", self.setKey, ["melee", True])
            self.accept("f-up", self.setKey, ["melee", False])
            self.accept("r", self.setKey, ["reload", True])
            self.accept("r-up", self.setKey, ["reload", False])
            self.accept("q", self.issueCommand, [0])
            self.accept("e", self.issueCommand, [1])
            self.commandSound = audio.FlatSound("sounds/command.ogg", 0.5)
            self.sprintSound = audio.FlatSound("sounds/sprint.ogg", 0.5)

    def sprint(self):
        if engine.inputEnabled:
            self.setKey("sprint", True)
            self.sprintSound.play()

    def toggleZoom(self):
        if self.zoomTime == -1 and not self.isPlatformMode:
            if self.zoomed:
                self.zoomTime = engine.clock.time
                self.currentCameraOffset = self.cameraOffset
                self.currentFov = self.fov
                self.desiredFov = self.defaultFov
                self.desiredCameraOffset = self.defaultCameraOffset
                self.mouse.setSpeed(self.defaultMouseSpeed)
                self.currentCrosshair = self.entity.components[self.activeWeapon].defaultCrosshair
                self.zoomed = not self.zoomed
            elif not self.entity.components[self.activeWeapon].reloadActive:
                self.zoomTime = engine.clock.time
                self.currentCameraOffset = self.defaultCameraOffset
                self.currentFov = self.defaultFov
                self.desiredFov = self.entity.components[self.activeWeapon].zoomedFov
                self.desiredCameraOffset = self.entity.components[self.activeWeapon].zoomedCameraOffset
                self.mouse.setSpeed(
                    self.entity.components[self.activeWeapon].zoomedMouseSpeed)
                self.currentCrosshair = self.entity.components[self.activeWeapon].zoomedCrosshair
                self.zoomed = not self.zoomed

    def setPlatformMode(self, mode):
        self.isPlatformMode = mode

    def issueCommand(self, id):
        if engine.inputEnabled:
            actors = [x for x in self.entity.getTeam(
            ).actors if x.teamIndex == id]
            if len(actors) > 0:
                actor = actors[0]
                if engine.clock.time - self.lastCommandTimes[id] < 0.4:
                    # Player double-tapped the key. Special attack.
                    # -1 means special attack
                    self.commands.append((actor.getId(), -1))
                elif self.targetedEnemy is not None and self.targetedEnemy.active:
                    # Set the bot's target entity
                    self.commands.append(
                        (actor.getId(), self.targetedEnemy.getId()))
                else:
                    # No target. Return to the player.
                    self.commands.append((actor.getId(), self.entity.getId()))
                self.commandSound.play()
                self.lastCommandTimes[id] = engine.clock.time

    def setKey(self, key, value):
        self.keyMap[key] = value and engine.inputEnabled

    def melee(self):
        self.entity.components[0].show()
        self.entity.components[0].fire()

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        if self.keyMap["melee"]:
            if self.zoomed:
                self.toggleZoom()
            self.melee()
            self.keyMap["melee"] = False
        if self.keyMap["reload"]:
            if self.zoomed:
                self.toggleZoom()
            self.reload()
            self.keyMap["reload"] = False
        if self.keyMap["jump"]:
            if engine.clock.time - self.lastJump > 0.25 and aiWorld.testCollisions(
                    self.entity.collisionNodePath).getNumEntries() > 0:
                self.lastJump = engine.clock.time
                self.entity.setLinearVelocity(
                    self.entity.getLinearVelocity() + Vec3(0, 0, 16))
        if self.keyMap["switch-weapon"]:
            self.keyMap["switch-weapon"] = False
            if self.activeWeapon == 1:
                self.activeWeapon = 2
            else:
                self.activeWeapon = 1
            self.activeWeapon = min(
                self.activeWeapon, len(self.entity.components) - 1)
            if self.zoomed:
                self.toggleZoom()
            self.currentCrosshair = self.entity.components[self.activeWeapon].defaultCrosshair
        if self.keyMap["alternate-action"]:
            self.keyMap["alternate-action"] = False
            if self.entity.special is not None:
                self.entity.special.enable()

        if self.currentCrosshair == -1:
            self.currentCrosshair = self.entity.components[self.activeWeapon].defaultCrosshair

        if self.zoomTime != -1:
            blend = min(1.0, (engine.clock.time -
                              self.zoomTime) / self.totalZoomTime)
            self.fov = self.currentFov + \
                ((self.desiredFov - self.currentFov) * blend)
            self.cameraOffset = self.currentCameraOffset + \
                ((self.desiredCameraOffset - self.currentCameraOffset) * blend)
            if base.camLens is not None:  # If we're a daemon.
                base.camLens.setFov(self.fov)
            if blend >= 1.0:
                self.zoomTime = -1

        self.mouse.update()
        self.angleX = self.mouse.getX()
        self.angleY = self.mouse.getY()

        angleX = self.angleX

        if self.isPlatformMode:
            angleX = 0

        move = True
        if self.keyMap["left"] and self.keyMap["forward"]:
            angleX += (.75 * math.pi)
        elif self.keyMap["left"] and self.keyMap["down"]:
            angleX += (.25 * math.pi)
        elif self.keyMap["right"] and self.keyMap["forward"]:
            angleX -= (.75 * math.pi)
        elif self.keyMap["right"] and self.keyMap["down"]:
            angleX -= (.25 * math.pi)
        elif self.keyMap["left"]:
            angleX += (math.pi / 2)
        elif self.keyMap["right"]:
            angleX -= (math.pi / 2)
        elif self.keyMap["forward"]:
            angleX += math.pi
        elif not self.keyMap["down"]:
            move = False
        angularVel = self.entity.getAngularVelocity()

        maxSpeed = self.maxSpeed
        torque = self.torque
        self.sprinting = self.keyMap["sprint"]
        if self.keyMap["sprint"]:
            maxSpeed *= 2
            torque *= 2
        if move:
            self.entity.addTorque(Vec3(engine.impulseToForce(
                torque * math.cos(angleX)), engine.impulseToForce(-torque * math.sin(angleX)), 0))
            if angularVel.length() > maxSpeed:
                angularVel.normalize()
                self.entity.setAngularVelocity(angularVel * maxSpeed)
        else:
            self.entity.addTorque(Vec3(engine.impulseToForce(-angularVel.getX() * 20),
                                       engine.impulseToForce(-angularVel.getY() * 20),
                                       engine.impulseToForce(-angularVel.getZ() * 20)))

        if self.isPlatformMode:
            self.pickRay.setOrigin(Point3(self.entity.getPosition()))
            self.pickRay.setDirection(Vec3(0, -1, 0))
        else:
            camera.setHpr(-math.degrees(self.angleX) + entityGroup.cameraShakeX *
                          0.5, math.degrees(self.angleY) + entityGroup.cameraShakeY * 0.5, 0)
            cameraPos = render.getRelativeVector(camera, self.cameraOffset)
            camera.setPos(self.entity.getPosition() + cameraPos)
            self.pickRay.setFromLens(base.camNode, 0, 0)

        target = None
        if engine.clock.time - self.lastTargetCheck > 0.05:
            self.lastTargetCheck = engine.clock.time
            queue = aiWorld.getRayCollisionQueue(self.pickRayNP)
            camDistance = (camera.getPos() - self.entity.getPosition()
                           ).length() + self.entity.radius
            for i in range(queue.getNumEntries()):
                entry = queue.getEntry(i)
                t = entry.getSurfacePoint(render)
                targetVector = camera.getPos() - t
                if camDistance < targetVector.length():
                    target = t
                    break
        if target is None:
            self.targetPos = camera.getPos() + (render.getRelativeVector(camera,
                                                                         Vec3(0, 1, 0)) * self.targetDistance)
        else:
            self.targetPos = target
            self.targetDistance = (target - camera.getPos()).length()

        origin = camera.getPos()
        dir = render.getRelativeVector(camera, Vec3(0, 1, 0))
        closestDot = 0.95
        self.targetedEnemy = None
        for enemy in (
            x for x in list(entityGroup.entities.values()) if isinstance(
                x, entities.DropPod) or (
                (isinstance(
                x, entities.Actor) and not x.getTeam().isAlly(
                    self.entity.getTeam()) and not x.cloaked))):
            vector = enemy.getPosition() - origin
            vector.normalize()
            dot = vector.dot(dir)
            if dot > closestDot:
                closestDot = dot
                self.targetedEnemy = enemy

        self.entity.components[self.activeWeapon].zoomed = self.zoomed

        if self.keyMap["fire"]:
            if target is not None:
                direction = target - self.entity.getPosition()
            else:
                direction = render.getRelativeVector(
                    self.pickRayNP, self.pickRay.getDirection())
                direction = (camera.getPos() + (direction * 500)
                             ) - self.entity.getPosition()
            direction.normalize()
            self.entity.components[self.activeWeapon].fire()
            if self.entity.components[self.activeWeapon].reloadActive and self.zoomed:
                self.toggleZoom()  # Zoom out if the weapon reloaded automatically

        p = DroidController.serverUpdate(
            self, aiWorld, entityGroup, packetUpdate)

        # Update camera position if it's been updated by
        # DroidController.serverUpdate. That way the screen doesn't jitter.
        if not self.isPlatformMode:
            camera.setPos(self.entity.getPosition() + cameraPos)

        p.add(net.Boolean(self.sprinting))
        cmds = len(self.commands)
        p.add(net.Uint8(cmds))
        if cmds > 0:
            self.addCriticalPacket(p, packetUpdate)
        for c in self.commands:
            p.add(net.Uint8(c[0]))  # The ID of our actor
            p.add(net.Boolean(c[1] == -1))  # True if this is a special attack
            if c[1] != -1:  # Setting the bot's target
                p.add(net.Uint8(c[1]))  # The ID of the target entity
        del self.commands[:]

        return p

    def clientUpdate(self, aiWorld, entityGroup, iterator=None):
        DroidController.clientUpdate(self, aiWorld, entityGroup, iterator)

        if iterator is not None:
            self.sprinting = net.Boolean.getFrom(iterator)
            cmds = net.Uint8.getFrom(iterator)
            for i in range(cmds):
                id = net.Uint8.getFrom(iterator)
                entity = entityGroup.getEntity(id)
                if entity is None:  # Do nothing
                    if net.Boolean.getFrom(iterator):
                        net.Uint8.getFrom(iterator)
                else:
                    controller = entity.controller
                    if net.Boolean.getFrom(iterator):
                        controller.enableSpecial()
                    else:
                        target = entityGroup.getEntity(
                            net.Uint8.getFrom(iterator))
                        if target == self.entity:
                            controller.setTarget(None)
                        else:
                            controller.setTarget(target)

        particles.UnitHighlightParticleGroup.draw(self.entity.getPosition(
        ), self.entity.getTeam().color, self.entity.radius + 0.4)

        weapon = self.entity.components[self.activeWeapon]
        if weapon.selected and self.sprinting:
            weapon.hide()
        # If the melee claw isn't ready
        if not self.entity.components[0].isReady():
            weapon.hide()
        elif not weapon.selected and not self.sprinting:
            weapon.show()

    def delete(self, killed=False):
        # If we're a local player and we're not running in a daemon.
        if self.entity.isLocal and base.camLens is not None:
            base.camLens.setFov(self.defaultFov)
        DroidController.delete(self, killed)


class AIController(DroidController):
    """The AIController uses the ai module's pathfinding algorithms to go places.
    At the moment, only BasicDroid actors are supported."""

    def __init__(self):
        DroidController.__init__(self)
        self.nearestEnemy = None
        self.targetedEnemy = None
        self.moving = False
        self.path = ai.Path()
        self.lastAiNode = None
        self.lastTargetAiNode = None
        self.lastPathFind = engine.clock.time + random() + 1.0
        self.lastMovementUpdate = engine.clock.time + random() + 1.0
        self.direction = Vec3()
        self.lastShot = 0
        self.lastTargetCheck = 0
        self.enemyLastVisible = False
        self.lastDodgeDirectionChange = 0
        self.reverseDodgeDirection = False

    def buildSpawnPacket(self):
        p = DroidController.buildSpawnPacket(self)
        p.add(net.Uint8(self.entity.teamIndex))
        return p

    @staticmethod
    def readSpawnPacket(aiWorld, entityGroup, iterator, entity=None):
        entity = entities.BasicDroid(
            aiWorld.world, aiWorld.space, AIController(), local=False)
        entity = DroidController.readSpawnPacket(
            aiWorld, entityGroup, iterator, entity)
        entity.teamIndex = net.Uint8.getFrom(iterator)
        return entity

    def actorDamaged(self, entity, damage, ranged):
        DroidController.actorDamaged(self, entity, damage, ranged)
        if not isinstance(entity, entities.BasicDroid) or entity.cloaked:
            return

    def enableSpecial(self):
        if self.entity.special is not None:
            self.entity.special.enable()

    def setTarget(self, target):
        self.targetedEnemy = target

    def pathCallback(self, path):
        self.path = path

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        # PATH FIND UPDATE
        if engine.clock.time - self.lastPathFind > 1.0:
            self.lastPathFind = engine.clock.time

            player = self.entity.getTeam().getPlayer()
            if player is None and (
                    self.targetedEnemy is None or not self.targetedEnemy.active):
                self.targetedEnemy = aiWorld.getNearestDropPod(
                    entityGroup, self.entity.getPosition())
                if self.targetedEnemy is None:
                    self.targetedEnemy = aiWorld.getNearestEnemy(
                        entityGroup, self.entity.getPosition(), self.entity.getTeam())
            if self.targetedEnemy is not None and self.targetedEnemy.active and isinstance(
                    self.targetedEnemy, entities.Actor):
                self.nearestEnemy = self.targetedEnemy
            elif self.nearestEnemy is None or not self.nearestEnemy.active or (self.nearestEnemy.getPosition() - self.entity.getPosition()).length() > 15:
                self.nearestEnemy = aiWorld.getNearestEnemy(
                    entityGroup, self.entity.getPosition(), self.entity.getTeam())

            aiNode = aiWorld.navMesh.getNode(
                self.entity.getPosition(), self.entity.radius, self.lastAiNode)
            targetAiNode = None
            target = None
            if self.targetedEnemy is not None and self.targetedEnemy.active:
                target = self.targetedEnemy
            elif self.entity.getTeam().getPlayer() is not None and self.entity.getTeam().getPlayer().active:
                target = self.entity.getTeam().getPlayer()
            if target is not None:
                targetAiNode = aiWorld.navMesh.getNode(
                    target.getPosition(), target.radius)
                if (target.getPosition() -
                        self.entity.getPosition()).length() > 10:
                    if (
                        targetAiNode is not None and aiNode is not None) and (
                        targetAiNode != self.lastTargetAiNode or (
                            aiNode != self.lastAiNode and (
                                aiNode not in self.path.nodes))):
                        ai.requestPath(
                            self.pathCallback,
                            aiNode,
                            targetAiNode,
                            self.entity.getPosition(),
                            target.getPosition(),
                            self.entity.radius + 0.5)
                else:
                    self.path.clear()
                    self.path.end = target.getPosition() + Vec3(uniform(-12, 12), uniform(-12, 12), 0)
            self.lastAiNode = aiNode
            self.lastTargetAiNode = targetAiNode

        # PATH FIND TO NEXT NODE
        if engine.clock.time - self.lastMovementUpdate > 0.2:
            self.lastMovementUpdate = engine.clock.time
            self.moving = False
            self.direction = Vec3()
            if self.path is not None and self.path.hasNext():
                self.moving = True
                self.direction = self.path.current() - self.entity.getPosition()
                if self.direction.length() < self.entity.radius + 2:
                    next(self.path)
                self.direction.normalize()
            elif self.path is not None and self.path.end is not None and (self.path.end - self.entity.getPosition()).length() > 4:
                self.direction = self.path.end - self.entity.getPosition()
                self.direction.normalize()
                self.moving = True

            # Simple obstacle avoidance
            obj = entityGroup.getNearestPhysicsEntity(
                self.entity.getPosition())
            if obj is not None:
                diff = obj.getPosition() - self.entity.getPosition()
                if diff.length() < obj.radius + self.entity.radius + 1.5:
                    diff.setZ(0)
                    diff.normalize()
                    if self.direction.dot(diff) > 0.7:
                        up = Vec3(0, 0, 1)
                        self.direction = diff.cross(up)
                        if engine.clock.time - self.lastDodgeDirectionChange > 1.0:
                            self.lastDodgeDirectionChange = engine.clock.time
                            self.reverseDodgeDirection = random() > 0.5
                        if self.reverseDodgeDirection:
                            self.direction *= -1

        # PHYSICS/MOVEMENT UPDATE
        angularVel = self.entity.getAngularVelocity()
        if self.moving:
            self.entity.addTorque(
                Vec3(
                    engine.impulseToForce(
                        -self.torque * self.direction.getY()),
                    engine.impulseToForce(
                        self.torque * self.direction.getX()),
                    0))
            if angularVel.length() > self.maxSpeed:
                angularVel.normalize()
                self.entity.setAngularVelocity(angularVel * self.maxSpeed)
        else:
            self.entity.addTorque(Vec3(engine.impulseToForce(-angularVel.getX() * 6),
                                       engine.impulseToForce(-angularVel.getY() * 6),
                                       engine.impulseToForce(-angularVel.getZ() * 6)))

        # WEAPON UPDATE
        weapon = self.entity.components[self.activeWeapon]
        if weapon.burstTimer == -1 and engine.clock.time - \
                weapon.burstDelayTimer >= weapon.burstDelay:
            if self.nearestEnemy is not None and self.nearestEnemy.active:
                vector = self.nearestEnemy.getPosition() - self.entity.getPosition()
                if vector.length() < weapon.range:
                    vector.normalize()
                    if engine.clock.time - self.lastTargetCheck > 1.0:
                        self.lastTargetCheck = engine.clock.time
                        self.enemyLastVisible = entityGroup.getEntityFromEntry(aiWorld.getFirstCollision(
                            self.entity.getPosition() + (vector * (self.entity.radius + 0.2)), vector)) == self.nearestEnemy
                    if self.enemyLastVisible:
                        weapon.burstTimer = engine.clock.time
                        weapon.burstDelayTimer = -1
                        weapon.burstTime = weapon.burstTimeBase * \
                            ((random() * 1.5) + 1)
                        weapon.shotDelay = weapon.shotDelayBase * \
                            ((random() * 1.5) + 1)

        if weapon.burstTimer != -1 and engine.clock.time - \
                weapon.burstTimer <= weapon.burstTime and self.nearestEnemy is not None and self.nearestEnemy.active:
            if engine.clock.time - self.lastShot > weapon.shotDelay:
                if weapon.fire():
                    weapon.burstDelayTimer = engine.clock.time
                    weapon.burstDelay = weapon.burstDelayBase * \
                        ((random() * 1.5) + 1)
                    self.lastShot = engine.clock.time
        else:
            weapon.burstTimer = -1

        if self.nearestEnemy is not None and self.nearestEnemy.active:
            self.targetPos = self.nearestEnemy.getPosition()
        if weapon.firing:
            vector = self.targetPos - self.entity.getPosition()
            distance = vector.length()
            vector /= distance
            coefficient = uniform(weapon.accuracy - 1.0,
                                  1.0 - weapon.accuracy) * 2.0
            up = Vec3(0, 0, 1)
            cross = vector.cross(up)
            self.targetPos += up * coefficient
            self.targetPos += cross * coefficient

        p = DroidController.serverUpdate(
            self, aiWorld, entityGroup, packetUpdate)

        return p

    def clientUpdate(self, aiWorld, entityGroup, iterator=None):
        DroidController.clientUpdate(self, aiWorld, entityGroup, iterator)


class Special(DirectObject):

    def __init__(self, actor):
        self.actor = actor
        self.lifeTime = 10
        self.timer = -1
        self.enabled = False
        self.newEnabled = False
        self.enabledChanged = False
        self.criticalPackets = []
        # Passive specials (like shields) need to cancel out the order to set
        # the bot's target enemy.
        self.passive = True

    def addCriticalPacket(self, p, packetUpdate):
        # If we have a critical packet on an update frame, and we add it to the critical packet queue,
        # it will get sent again on the next update frame.
        # So, we don't want that to happen.
        if not packetUpdate and p not in self.criticalPackets:
            self.criticalPackets.append(p)

    def enable(self):
        if self.actor.getTeam().specialAvailable():
            self.actor.getTeam().enableSpecial()
            self.timer = engine.clock.time
            self.newEnabled = True

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        if self.timer > 0 and engine.clock.time - self.timer >= self.lifeTime:
            self.newEnabled = False
        p = net.Packet()
        if packetUpdate:
            p.add(net.Uint8(len(self.criticalPackets) + 1))
            for packet in self.criticalPackets:
                p.add(packet)
            del self.criticalPackets[:]
        else:
            p.add(net.Uint8(1))
        self.enabled = self.newEnabled
        p.add(net.Boolean(self.enabled))
        p.add(net.Boolean(self.newEnabled != self.enabled))
        if self.newEnabled != self.enabled:
            p.add(net.HighResFloat(self.timer))
            self.addCriticalPacket(p, packetUpdate)
        return p

    def clientUpdateStart(self, aiWorld, entityGroup, iterator=None):
        if iterator is not None:
            criticalPackets = net.Uint8.getFrom(iterator)
            for _ in range(criticalPackets):
                self.clientUpdate(aiWorld, entityGroup, iterator)

    def clientUpdate(self, aiWorld, entityGroup, iterator=None):
        if iterator is not None:
            self.enabled = net.Boolean.getFrom(iterator)
            if net.Boolean.getFrom(iterator):
                self.timer = net.HighResFloat.getFrom(iterator)
                if self.passive:
                    # Cancel the target setting
                    self.actor.controller.targetedEnemy = self.actor.controller.lastTargetedEnemy

    def delete(self):
        pass


class KamikazeSpecial(Special):
    def __init__(self, actor):
        Special.__init__(self, actor)
        self.specialSound = audio.SoundPlayer("kamikaze-special")
        self.lifeTime = 3
        self.triggered = False

    def clientUpdate(self, aiWorld, entityGroup, iterator=None):
        Special.clientUpdate(self, aiWorld, entityGroup, iterator)
        if not self.actor.active:
            return
        if self.enabled:
            if not self.triggered:
                self.specialSound.play(entity=self.actor)
            self.triggered = True
            for entity in list(entityGroup.entities.values()):
                if isinstance(
                    entity, entities.ObjectEntity) and not (
                    isinstance(
                        entity, entities.Actor) and entity.getTeam().isAlly(
                        self.actor.getTeam())):
                    vector = self.actor.getPosition() - entity.getPosition()
                    distance = vector.length()
                    vector /= distance
                    vector *= (400.0 / max(6.0, distance))
                    entity.addForce(engine.impulseToForce(
                        vector.getX(), vector.getY(), vector.getZ()))
        elif self.triggered:
            entityGroup.shakeCamera()
            explosionSound = audio.SoundPlayer("large-explosion")
            pos = self.actor.getPosition()
            explosionSound.play(position=pos)
            entityGroup.explode(pos, force=6000, damage=300,
                                damageRadius=125, sourceEntity=self.actor)
            self.actor.delete(entityGroup, killed=False, localDelete=False)

    def delete(self):
        self.specialSound.delete()


class ShieldSpecial(Special):
    def __init__(self, actor):
        Special.__init__(self, actor)
        self.shieldSound = audio.SoundPlayer("shield")
        self.lastEnabled = False

    def clientUpdate(self, aiWorld, entityGroup, iterator=None):
        Special.clientUpdate(self, aiWorld, entityGroup, iterator)
        if not self.actor.active:
            return
        if self.enabled and not self.lastEnabled:
            self.shieldSound.play(entity=self.actor)
        self.lastEnabled = self.enabled
        self.actor.setShielded(True)
        player = self.actor.getTeam().getPlayer()
        if player is not None and player != self.actor:
            player.setShielded(
                self.enabled or player.initialSpawnShieldEnabled or isinstance(
                    player.special, ShieldSpecial))
        for actor in (
                x for x in self.actor.getTeam().actors if x != self.actor):
            actor.setShielded(
                self.enabled or actor.initialSpawnShieldEnabled or isinstance(
                    actor.special, ShieldSpecial))

    def delete(self):
        Special.delete(self)
        for actor in (
                x for x in self.actor.getTeam().actors if x != self.actor):
            actor.setShielded(
                False or actor.initialSpawnShieldEnabled or isinstance(
                    actor.special, ShieldSpecial))
        player = self.actor.getTeam().getPlayer()
        if player is not None:
            player.setShielded(
                False or player.initialSpawnShieldEnabled or isinstance(
                    player.special, ShieldSpecial))


class CloakSpecial(Special):
    def __init__(self, actor):
        Special.__init__(self, actor)
        self.cloakSound = audio.SoundPlayer("shield")
        self.lastEnabled = False

    def clientUpdate(self, aiWorld, entityGroup, iterator=None):
        Special.clientUpdate(self, aiWorld, entityGroup, iterator)
        if not self.actor.active:
            return
        if self.enabled and not self.lastEnabled:
            self.cloakSound.play(entity=self.actor)
        self.lastEnabled = self.enabled
        for actor in (
                x for x in self.actor.getTeam().actors if x != self.actor):
            actor.setCloaked(self.enabled or isinstance(
                actor.special, CloakSpecial))
        if self.actor.getTeam().getPlayer() is not None:
            self.actor.getTeam().getPlayer().setCloaked(
                self.enabled or isinstance(
                    self.actor.getTeam().getPlayer().special,
                    CloakSpecial))
        self.actor.setCloaked(True)

    def delete(self):
        Special.delete(self)
        for actor in (
                x for x in self.actor.getTeam().actors if x != self.actor):
            actor.setCloaked(False or isinstance(actor.special, CloakSpecial))
        if self.actor.getTeam().getPlayer() is not None:
            self.actor.getTeam().getPlayer().setCloaked(False or isinstance(
                self.actor.getTeam().getPlayer().special, CloakSpecial))


class AwesomeSpecial(Special):
    def __init__(self, actor):
        Special.__init__(self, actor)
        self.originalMaxSpeed = self.actor.controller.maxSpeed
        self.originalFireTimes = dict()
        for x in self.actor.getWeapons():
            self.originalFireTimes[x] = (
                x.fireTime, x.reloadTime if isinstance(
                    x, components.Gun) else 0)
        self.lastParticleSpawn = 0
        if isinstance(self.actor.controller, AIController):
            self.originalAccuracy = self.actor.components[0].accuracy
            self.originalRange = self.actor.components[0].range

    def clientUpdate(self, aiWorld, entityGroup, iterator=None):
        Special.clientUpdate(self, aiWorld, entityGroup, iterator)
        if not self.actor.active:
            return
        multiplier = 1.0
        if self.enabled:
            multiplier = 6.0
            if engine.clock.time - self.lastParticleSpawn > 0.05:
                self.lastParticleSpawn = engine.clock.time
                particles.add(particles.SparkParticleGroup(
                    self.actor.getPosition()))
            self.actor.health = self.actor.maxHealth
        weapon = self.actor.components[self.actor.controller.activeWeapon]
        if isinstance(self.actor.controller, AIController):
            weapon.range = self.originalRange * multiplier
            weapon.accuracy = min(1.0, self.originalAccuracy * multiplier)
        self.actor.controller.maxSpeed = self.originalMaxSpeed * multiplier
        weapon.fireTime = self.originalFireTimes[weapon][0] / multiplier
        if isinstance(weapon, components.Gun):
            weapon.reloadTime = self.originalFireTimes[weapon][1] / multiplier


class RocketSpecial(Special):
    def __init__(self, actor):
        Special.__init__(self, actor)
        self.lifeTime = 1.7
        self.target = None
        self.start = None
        self.particleGroup = None
        self.rocketSound = audio.SoundPlayer("rocket")
        self.passive = False

    def serverUpdate(self, aiWorld, entityGroup, packetUpdate):
        p = Special.serverUpdate(self, aiWorld, entityGroup, packetUpdate)
        if self.enabled:
            if self.target is None:
                if self.actor.controller.targetedEnemy is not None and self.actor.controller.targetedEnemy.active:
                    self.target = self.actor.controller.targetedEnemy.getPosition()
                else:
                    target = aiWorld.getNearestEnemy(
                        entityGroup, self.actor.getPosition(), self.actor.getTeam())
                    if target is not None:
                        self.target = target.getPosition()
                self.rocketSound.play(position=self.start)
                self.start = self.actor.getPosition()
            if self.target is not None:
                scale = float(engine.clock.time - self.timer) / self.lifeTime
                offset = self.target - self.start
                offset *= scale
                height = (0.25 - ((scale - 0.5) * (scale - 0.5))) * 75
                offset.setZ(offset.getZ() + height)
                self.actor.setPosition(self.start + offset)
        return p

    def clientUpdate(self, aiWorld, entityGroup, iterator=None):
        Special.clientUpdate(self, aiWorld, entityGroup, iterator)
        if not self.actor.active:
            return
        if self.enabled:
            if not self.rocketSound.isPlaying():
                self.rocketSound.play(entity=self.actor)
            pos = self.actor.getPosition()
            if self.particleGroup is None:
                self.particleGroup = particles.SmokeParticleGroup(pos)
                particles.add(self.particleGroup)
            self.particleGroup.setPosition(pos)
        elif self.target is not None:
            grenadeSound = audio.SoundPlayer("grenade")
            grenadeSound.play(position=self.actor.getPosition())
            entityGroup.shakeCamera()
            entityGroup.explode(
                self.actor.getPosition(),
                force=4000,
                damage=250,
                damageRadius=40,
                sourceEntity=self.actor)
            self.target = None


class SpectatorController(Controller):
    "The SpectatorController lets the camera wander around and watch the game."

    def __init__(self):
        Controller.__init__(self)
        self.mouse = engine.Mouse()
        self.accept("a", self.setKey, ["left", 1])
        self.accept("d", self.setKey, ["right", 1])
        self.accept("w", self.setKey, ["forward", 1])
        self.accept("s", self.setKey, ["back", 1])
        self.accept("a-up", self.setKey, ["left", 0])
        self.accept("d-up", self.setKey, ["right", 0])
        self.accept("w-up", self.setKey, ["forward", 0])
        self.accept("s-up", self.setKey, ["back", 0])
        self.accept("space", self.setKey, ["raise", 1])
        self.accept("space-up", self.setKey, ["raise", 0])
        self.accept("control", self.setKey, ["lower", 1])
        self.accept("control-up", self.setKey, ["lower", 0])
        self.keyMap = {"left": 0, "right": 0, "forward": 0,
                       "back": 0, "raise": 0, "lower": 0}

    def setKey(self, key, value):
        self.keyMap[key] = value

    def serverUpdate(self, aiWorld, entityGroup, data):
        p = Controller.serverUpdate(self, aiWorld, entityGroup, data)
        "Updates the camera position, cursor position, and picking ray."

        self.mouse.update()

        angleX = -math.radians(camera.getH())
        angleY = math.radians(camera.getP())

        angleX += self.mouse.getDX()
        angleY += self.mouse.getDY()

        speed = engine.clock.timeStep * 40 if engine.clock.timeStep > 0 else 1
        velocity = Vec3(0, 0, 0)
        if self.keyMap["forward"] == 1:
            velocity += Vec3(speed * math.sin(angleX), speed *
                             math.cos(angleX), speed * math.sin(angleY))
        if self.keyMap["back"] == 1:
            velocity += Vec3(-speed * math.sin(angleX), -speed *
                             math.cos(angleX), -speed * math.sin(angleY))
        if self.keyMap["left"] == 1:
            velocity += Vec3(speed * -math.sin(angleX + (math.pi / 2)),
                             speed * -math.cos(angleX + (math.pi / 2)), 0)
        if self.keyMap["right"] == 1:
            velocity += Vec3(speed * math.sin(angleX + (math.pi / 2)),
                             speed * math.cos(angleX + (math.pi / 2)), 0)
        if self.keyMap["raise"] == 1:
            velocity += Vec3(0, 0, speed)
        if self.keyMap["lower"] == 1:
            velocity += Vec3(0, 0, -speed)

        camera.setPos(camera.getPos() + velocity)
        camera.setHpr(-math.degrees(angleX), math.degrees(angleY), 0)

        return None

    def delete(self):
        Controller.delete(self)


class EditController(Controller):
    "The EditController handles all user input for the level editor."

    def __init__(self, aiWorld, entityGroup, map, ui, enableEdit=True):
        Controller.__init__(self)
        self.ui = ui
        self.enableEdit = enableEdit
        self.map = map
        self.pickRayNode = CollisionNode("pickRayNode")
        self.pickRayNP = camera.attachNewNode(self.pickRayNode)
        self.pickRay = CollisionRay()
        self.pickRayNode.setIntoCollideMask(BitMask32(0))
        self.pickRayNode.setFromCollideMask(BitMask32(1))
        self.pickRayNode.addSolid(self.pickRay)
        self.cameraOffset = Vec3(40, 0, 0)
        self.accept("a", self.setKey, ["left", 1])
        self.accept("d", self.setKey, ["right", 1])
        self.accept("w", self.setKey, ["forward", 1])
        self.accept("s", self.setKey, ["back", 1])
        self.accept("a-up", self.setKey, ["left", 0])
        self.accept("d-up", self.setKey, ["right", 0])
        self.accept("w-up", self.setKey, ["forward", 0])
        self.accept("s-up", self.setKey, ["back", 0])
        self.accept("1", self.selectTool, [1])
        self.accept("2", self.selectTool, [2])
        self.accept("3", self.selectTool, [3])
        self.accept("4", self.selectTool, [4])
        self.accept("5", self.selectTool, [5])
        self.accept("6", self.selectTool, [6])
        self.accept("7", self.selectTool, [7])
        self.accept("8", self.selectTool, [8])
        self.accept("9", self.selectTool, [9])
        self.accept("space", self.setKey, ["raise", 1])
        self.accept("space-up", self.setKey, ["raise", 0])
        self.accept("control", self.setKey, ["lower", 1])
        self.accept("control-up", self.setKey, ["lower", 0])
        self.accept("mouse1", self.select, [aiWorld, entityGroup])
        self.accept("mouse1-up", self.mouseUp)
        self.accept("mouse3", self.setKey, ["rotate", 1])
        self.accept("mouse3-up", self.setKey, ["rotate", 0])
        self.accept("enter", self.save, [aiWorld, entityGroup])
        self.accept("z", self.undo, [aiWorld, entityGroup])
        self.accept("escape", engine.exit)
        self.keyMap = {"left": 0, "right": 0, "forward": 0,
                       "back": 0, "raise": 0, "lower": 0, "rotate": 0}
        self.angleX = math.radians(45)
        self.angleY = math.radians(-15)
        self.pos = Vec3(0, 0, 0)
        self.savedPoint = None
        self.selectedTool = 1
        self.rotating = False
        # Aspect ratio corrects for horizontal scaling when calculating the
        # cursor position / picking ray.
        self.mouseDown = False
        self.spawnedObjects = []
        self.clickTime = 0

    def save(self, aiWorld, entityGroup):
        try:
            self.map.save(aiWorld, entityGroup)
        except BaseException:
            import traceback
            exceptionData = traceback.format_exc()
            print(exceptionData)
            engine.log.info(exceptionData)

    def undo(self, aiWorld, entityGroup):
        if len(self.spawnedObjects) > 0:
            obj = self.spawnedObjects.pop()
            if isinstance(obj, engine.SpawnPoint):
                obj.delete()
                if isinstance(obj, engine.Dock):
                    aiWorld.docks.remove(obj)
                else:
                    aiWorld.spawnPoints.remove(obj)
            else:
                obj.delete(entityGroup)
                entityGroup.clearDeletedEntities()

    def selectTool(self, tool):
        "Changes the selected edit tool."
        self.selectedTool = tool
        self.savedPoint = None

    def setKey(self, key, value):
        self.keyMap[key] = value

    def mouseUp(self):
        self.mouseDown = False

    def select(self, aiWorld, entityGroup):
        "Click event handler. Performs one of several actions based on the selected edit tool."
        if not self.enableEdit:
            return
        entry = aiWorld.getRayFirstCollision(self.pickRayNP)
        if entry is None:
            return
        self.mouseDown = True
        self.clickTime = engine.clock.time
        target = entry.getSurfacePoint(render)
        if self.selectedTool == 1:
            # Make a physics entity
            filename = self.ui.currentPhysicsEntityFile
            if vfs.exists("maps/" + filename + ".txt"):
                directory = "maps/" + filename.rpartition("/")[0]
                data = vfs.readFile("maps/" + filename + ".txt", 1)
                obj = entities.PhysicsEntity(
                    aiWorld.world, aiWorld.space, data, directory, filename)
                obj.setPosition(target + Vec3(0, 0, obj.vradius))
                normal = entry.getSurfaceNormal(render)
                obj.setRotation(Vec3(0,
                                     math.degrees(-math.atan2(normal.getY(),
                                                              normal.getZ())),
                                     math.degrees(math.atan2(normal.getX(),
                                                             normal.getZ()))))
                entityGroup.spawnEntity(obj)
                self.spawnedObjects.append(obj)
        elif self.selectedTool == 2:
            # Make a dock
            dock = engine.Dock(aiWorld.space, len(aiWorld.docks))
            normal = entry.getSurfaceNormal(render)
            dock.setPosition(target + Vec3(0, 0, dock.vradius))
            dock.setRotation(Vec3(0,
                                  math.degrees(-math.atan2(normal.getY(),
                                                           normal.getZ())),
                                  math.degrees(math.atan2(normal.getX(),
                                                          normal.getZ()))))
            aiWorld.docks.append(dock)
            self.spawnedObjects.append(dock)
        elif self.selectedTool == 3:
            # Make a spawn point
            geom = engine.SpawnPoint(aiWorld.space)
            geom.setPosition(Vec3(target))
            normal = entry.getSurfaceNormal(render)
            geom.setRotation(Vec3(0,
                                  math.degrees(-math.atan2(normal.getY(),
                                                           normal.getZ())),
                                  math.degrees(math.atan2(normal.getX(),
                                                          normal.getZ()))))
            aiWorld.spawnPoints.append(geom)
            self.spawnedObjects.append(geom)
        elif self.selectedTool == 4:
            # Make vertical glass
            if self.savedPoint is None:
                self.savedPoint = Vec3(target)
            else:
                pos = (target + self.savedPoint) / 2.0
                dist = (target - self.savedPoint).length()
                glass = entities.Glass(aiWorld.world, aiWorld.space)
                glass.initGlass(aiWorld.world, aiWorld.space, dist, 10)
                glass.setPosition(pos + Vec3(0, 0, 5))
                v = target - self.savedPoint
                v.normalize()
                glass.setRotation(
                    Vec3(math.degrees(math.atan2(v.getY(), v.getX())), 0, 0))
                entityGroup.spawnEntity(glass)
                self.savedPoint = None
                self.spawnedObjects.append(glass)
        elif self.selectedTool == 5:
            # Make horizontal glass
            if self.savedPoint is None:
                self.savedPoint = Vec3(target)
            else:
                pos = (target + self.savedPoint) / 2.0
                width = target.getX() - self.savedPoint.getX()
                height = target.getY() - self.savedPoint.getY()
                glass = entities.Glass(aiWorld.world, aiWorld.space)
                glass.initGlass(
                    aiWorld.world,
                    aiWorld.space,
                    width if width >= 0 else width * -1,
                    height if height >= 0 else height * -1)
                glass.setPosition(pos)
                glass.setRotation(Vec3(0, 90, 0))
                entityGroup.spawnEntity(glass)
                self.savedPoint = None
                self.spawnedObjects.append(glass)
        elif self.selectedTool == 6:
            # Delete a physics entity, dock, or spawn point
            objects = [
                entityGroup.getNearestPhysicsEntity(target),
                aiWorld.getNearestDock(target),
                aiWorld.getNearestSpawnPoint(target)]
            obj = sorted(objects, key=lambda x: 100000 if x ==
                         None else (x.getPosition() - target).length())[0]
            if isinstance(obj, engine.SpawnPoint):
                obj.delete()
                if isinstance(obj, engine.Dock):
                    aiWorld.docks.remove(obj)
                else:
                    aiWorld.spawnPoints.remove(obj)
            else:
                obj.delete(entityGroup)
                entityGroup.clearDeletedEntities()

    def serverUpdate(self, aiWorld, entityGroup, data):
        p = Controller.serverUpdate(self, aiWorld, entityGroup, data)
        "Updates the camera position, cursor position, and picking ray."
        aspectRatio = float(base.win.getProperties().getXSize()) / \
            float(base.win.getProperties().getYSize())
        self.pickRay.setFromLens(
            base.camNode, self.ui.cursorX / aspectRatio, self.ui.cursorY)
        if self.mouseDown and len(
                self.spawnedObjects) > 0 and engine.clock.time - self.clickTime > 0.25:
            entry = aiWorld.getRayFirstCollision(self.pickRayNP)
            if entry is None:
                return
            target = entry.getSurfacePoint(render)
            obj = self.spawnedObjects[len(self.spawnedObjects) - 1]
            node = obj.node
            r = node.getR()
            p = node.getP()
            node.lookAt(target)
            obj.setRotation(Vec3(node.getH(), p, r))

        if self.keyMap["rotate"] == 1 or not self.enableEdit:
            self.angleX += self.ui.mouse.getDX()
            self.angleY += self.ui.mouse.getDY()

        speed = engine.clock.timeStep * 40 if engine.clock.timeStep > 0 else 1
        velocity = Vec3(0, 0, 0)
        if self.keyMap["forward"] == 1:
            velocity += Vec3(speed *
                             math.sin(self.angleX), speed *
                             math.cos(self.angleX), speed *
                             math.sin(self.angleY))
        if self.keyMap["back"] == 1:
            velocity += Vec3(-speed * math.sin(self.angleX), -speed *
                             math.cos(self.angleX), -speed * math.sin(self.angleY))
        if self.keyMap["left"] == 1:
            velocity += Vec3(speed * -math.sin(self.angleX + (math.pi / 2)),
                             speed * -math.cos(self.angleX + (math.pi / 2)), 0)
        if self.keyMap["right"] == 1:
            velocity += Vec3(speed * math.sin(self.angleX + (math.pi / 2)),
                             speed * math.cos(self.angleX + (math.pi / 2)), 0)
        if self.keyMap["raise"] == 1:
            velocity += Vec3(0, 0, speed)
        if self.keyMap["lower"] == 1:
            velocity += Vec3(0, 0, -speed)
        self.pos += velocity

        aimOffset = Vec3(math.sin(self.angleX), math.cos(
            self.angleX), math.sin(self.angleY))
        pos = self.pos
        camera.setPos(pos)
        camera.setHpr(-math.degrees(self.angleX), math.degrees(self.angleY), 0)
        return p

    def delete(self):
        self.pickRayNP.removeNode()
        Controller.delete(self)
