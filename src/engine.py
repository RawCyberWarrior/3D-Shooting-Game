import math
import os
import sys
import time
import traceback
from random import uniform

from . import ai
from . import audio
from . import controllers
from . import entities
from . import net
from . import particles
from . import ui
from . import constants

from panda3d.core import *
from panda3d.ode import *

from direct.actor.Actor import Actor
from direct.directnotify.DirectNotify import DirectNotify
from direct.filter.CommonFilters import CommonFilters
from direct.showbase.DirectObject import DirectObject
from direct.stdpy.file import *

clock = None  # Global clock
renderLit = None  # Parent nodepath for all objects that are affected by lights
renderObjects = None  # Parent nodepath for dynamic objects
renderEnvironment = None  # Parent nodepath for environment geometry
lights = []  # List of all light objects
lightNodes = []  # List of tuples containing lights and their nodepaths, respectively
cubeMap = None  # Cubemap for all environment mapping
reflectionBuffer = None  # Frame buffer for reflection effects
reflectionCamera = None  # Camera to render into reflection buffer
reflectionRenderTexture = None  # Texture for reflection shader to read from
filters = None  # Post processing filters
enableDistortionEffects = True
enableShaders = True
enablePostProcessing = False
enableAntialiasing = False
enableShadows = True
savedUsername = "Unnamed"
reflectionEffectsNeeded = False  # True if we're in a level with water
windowWidth = 800
windowHeight = 600
aspectRatio = float(windowWidth) / float(windowHeight)
isDaemon = False
cache = dict()
defaultFov = 70
shadowMapWidth = 1024
shadowMapHeight = 1024
mf = None
physicsEntityFileCache = dict()
paused = False
enablePause = False
modelFileSuffix = ""

map = None
inputEnabled = True

maps = []


def exit():
    if net.context is not None:
        net.context.delete()
    particles.ParticleGroup.end()
    sys.exit()


class Logger:

    def __init__(self):
        self.notify = DirectNotify().newCategory("core")

    def error(self, msg):
        self.notify.warning(msg)

    def warning(self, msg):
        self.notify.warning(msg)

    def info(self, msg):
        self.notify.info(msg)

    def debug(self, msg):
        self.notify.debug(msg)

    def exception(self, msg):
        self.notify.error(msg)


def togglePause():
    global paused
    if enablePause:
        paused = not paused


def loadConfigFile():
    global enableDistortionEffects
    global enableShaders
    global enablePostProcessing
    global enableShadows
    global enableAntialiasing
    global savedUsername
    global windowWidth
    global windowHeight
    global isFullscreen
    global aspectRatio
    try:
        configFile = open(os.path.join(
            os.path.expanduser("~"), "a3p-config"), "r")
    except IOError:
        return

    lines = configFile.read().split('\n')
    configFile.close()
    for line in lines:
        parts = line.split()
        if len(parts) == 0:
            continue
        if parts[0] == "enable-distortion-effects":
            enableDistortionEffects = parts[1] == "#t"
        elif parts[0] == "enable-shaders":
            enableShaders = parts[1] == "#t"
        elif parts[0] == "enable-post-processing":
            enablePostProcessing = parts[1] == "#t"
        elif parts[0] == "enable-shadows":
            enableShadows = parts[1] == "#t"
        elif parts[0] == "enable-antialiasing":
            enableAntialiasing = parts[1] == '#t'
        elif parts[0] == "username":
            savedUsername = " ".join(parts[1:])

    if windowHeight > 0:
        aspectRatio = float(windowWidth) / float(windowHeight)


def saveConfigFile():
    global enableDistortionEffects
    global enableShaders
    global enablePostProcessing
    global enableShadows
    global enableAntialiasing
    global savedUsername
    global windowWidth
    global windowHeight
    global aspectRatio
    aspectRatio = float(windowWidth) / float(windowHeight)
    configFile = open(os.path.join(os.path.expanduser("~"), "a3p-config"), "w")

    def boolToStr(a):
        if a:
            return "#t"
        else:
            return "#f"

    configFile.write("enable-distortion-effects " +
                     boolToStr(enableDistortionEffects) + "\n")
    configFile.write("enable-shaders " + boolToStr(enableShaders) + "\n")
    configFile.write("enable-post-processing " +
                     boolToStr(enablePostProcessing) + "\n")
    configFile.write("enable-shadows " + boolToStr(enableShadows) + "\n")
    configFile.write("enable-antialiasing " +
                     boolToStr(enableAntialiasing) + "\n")
    configFile.write("username " + savedUsername)
    configFile.close()


def cacheModel(filename):
    global modelFileSuffix
    model = loader.loadModel(filename + modelFileSuffix)
    model.reparentTo(renderLit)
    model.reparentTo(hidden)
    cache[filename] = model


def loadModel(filename):
    global modelFileSuffix
    if filename not in cache:
        return loader.loadModel(filename + modelFileSuffix)

    model = cache[filename]
    node = hidden.attachNewNode(filename)
    model.instanceTo(node)
    return node


def loadAnimation(filename, animations):
    global modelFileSuffix
    for anim in animations:
        animations[anim] += modelFileSuffix

    a = Actor(filename + modelFileSuffix, animations, allowAsyncBind=True)
    a.setBlend(animBlend=True, frameBlend=True)
    return a


def deleteModel(node, filename):
    node.removeNode()


def toggleGui():
    """Hides or Shows aspect2d nodepath"""

    if aspect2d.isHidden():
        aspect2d.show()
    else:
        aspect2d.hide()


def init(showFrameRate=False, daemon=False):
    """Initializes various global components, like audio, lighting, and the clock. Should be called once at the beginning of the program."""

    global renderLit
    global clock
    global renderObjects
    global renderEnvironment
    global log
    global reflectionBuffer
    global reflectionCamera
    global reflectionRenderTexture
    global defaultFov
    global enableShaders
    global enablePostProcessing
    global enableDistortionEffects
    global filters
    global isDaemon
    global mf
    global maps

    mf = None

    if not vfs.isDirectory("maps"):
        mf = Multifile()
        mf.openRead(ExecutionEnvironment.getEnvironmentVariable(
            "PKG_ROOT") + "/pkg.mf")

    isDaemon = daemon

    if not daemon:
        base.setBackgroundColor(2.0 / 255.0, 28.0 / 255.0, 53.0 / 255.0)

    log = Logger()
    sys.excepthook = exceptHook

    clock = Clock()
    base.disableMouse()  # Disable default mouse camera control
    base.setFrameRateMeter(showFrameRate)
    if not daemon:
        base.camNode.setCameraMask(BitMask32.bit(1))
        base.camLens.setFov(defaultFov)

    renderLit = render.attachNewNode("renderLit")
    renderObjects = renderLit.attachNewNode("renderObjects")
    renderEnvironment = renderLit.attachNewNode("renderEnvironment")

    controllers.init()
    ai.init()
    audio.init(dropOffFactor=1.4, distanceFactor=14, dopplerFactor=0.0)

    base.accept('f1', base.screenshot)
    base.accept('f2', toggleGui)

    numMaxDynamicLights = 0
    if enableShaders and not daemon:
        numMaxDynamicLights = 2

    for i in range(numMaxDynamicLights):
        light = PointLight("Light" + str(i))
        light.setColor(Vec4(0, 0, 0, 1))
        light.setAttenuation(Vec3(0, 0, 1))
        lightNode = renderLit.attachNewNode(light)
        lightNode.setPos(0, 0, 0)
        renderLit.setLight(lightNode)
        lightNodes.append((light, lightNode))

    if enableShaders and not daemon:
        shadersChanged()

    if enablePostProcessing and not daemon:
        postProcessingChanged()

    if enableAntialiasing and not daemon:
        antialiasingChanged()

    if not daemon:
        winprops = WindowProperties()
        props = FrameBufferProperties()
        props.setRgbColor(1)
        reflectionBuffer = base.graphicsEngine.makeOutput(
            base.pipe, "reflection-buffer", -2,
            props, winprops,
            GraphicsPipe.BFSizeTrackHost | GraphicsPipe.BFRefuseWindow,
            base.win.getGsg(), base.win)
        reflectionBuffer.setSort(-100)
        reflectionBuffer.setClearColor(Vec4(0, 0, 0, 0))
        reflectionRenderTexture = Texture()
        reflectionBuffer.addRenderTexture(
            reflectionRenderTexture,
            GraphicsOutput.RTMBindOrCopy,
            GraphicsOutput.RTPColor)
        reflectionCamera = base.makeCamera(
            reflectionBuffer,
            scene=render,
            lens=base.cam.node().getLens(),
            mask=BitMask32.bit(4))
        reflectionCamera.reparentTo(render)
        reflectionCamera.node().setActive(False)

    particles.init()
    maps = [x.split("\t") for x in readFile("maps/maps.txt").split("\n")]


def preloadModels():
    global modelFileSuffix
    if os.path.exists("models/basicdroid/BasicDroid.bam"):
        modelFileSuffix = ".bam"

    cacheModel("models/basicdroid/BasicDroid")
    cacheModel("models/basicdroid/chaingun")
    cacheModel("models/basicdroid/BasicDroid-lowres")
    cacheModel("models/basicdroid/sniper")
    cacheModel("models/basicdroid/shotgun")
    cacheModel("models/basicdroid/pistol")
    cacheModel("models/shield/shield")
    cacheModel("models/grenade/Grenade")
    cacheModel("models/fragment/Fragment")
    cacheModel("models/basicdroid/claw")
    cacheModel("models/basicdroid/claw-Retract")
    cacheModel("models/basicdroid/claw-Impale")
    cacheModel("models/fragment/GlassFragment")
    cacheModel("models/spawnpoint/SpawnPoint")
    cacheModel("models/spike/spike")
    cacheModel("models/pod/pod")
    cacheModel("maps/Block")
    cacheModel("maps/block1")
    cacheModel("models/crosshair/crosshair")


def antialiasingChanged():
    if enableAntialiasing:
        render.setAntialias(AntialiasAttrib.MAuto)
    else:
        render.clearAntialias()


def postProcessingChanged():
    global filters
    if enablePostProcessing:
        if filters is None:
            filters = CommonFilters(base.win, base.cam)

        render.setAttrib(LightRampAttrib.makeHdr1())
        filters.setBloom(intensity=1, size=2)
    else:
        if filters is not None:
            filters.delBloom()

    saveConfigFile()


def shadersChanged():
    if enableShaders:
        renderLit.setShaderAuto()
    else:
        renderLit.clearShader()

    saveConfigFile()


def shadowsChanged():
    global map
    if map is not None:
        if enableShadows:
            map.enableShadows()
        else:
            map.disableShadows()

    saveConfigFile()


def distortionEffectsChanged():
    if reflectionCamera is not None:
        reflectionCamera.node().setActive(
            enableDistortionEffects and reflectionEffectsNeeded)

    saveConfigFile()


def exceptHook(type, value, trace):
    # logging uses sys.exc_info to get exception data.
    sys.exc_info = lambda: (type, value, trace)
    exceptionData = traceback.format_exc()
    log.info(exceptionData)
    print(exceptionData)


def clearLights():
    global lights
    for light in lights:
        light.remove()

    del lights[:]


def update():
    "Updates global components. Basically the clock. Should be called once every frame, regardless of the game state."
    if not paused:
        clock.update()
    else:
        clock.timeStep = 0

    particles.ParticleGroup.begin()
    particles.update(not paused)


def endUpdate():
    particles.ParticleGroup.end()


class Clock:
    """Global clock; used just about everywhere.
    Starts at 0, units are in seconds.
    You can also change how fast it increments (slow down or speed up time).
    A new clock should be initialized every time a new Game is created."""

    def __init__(self):
        if sys.platform == "win32":
            self.timerFunction = time.clock
        else:
            self.timerFunction = time.time
        self._time = self.timerFunction()
        self.timeStep = 0
        self.lastFrameTime = self.time

    def update(self):
        "Call once every frame."
        self.lastFrameTime = self.time
        self._time = self.timerFunction()
        self.timeStep = min(0.1, max(0.005, self.time - self.lastFrameTime))

    @property
    def time(self):
        return self._time


def readFile(file):
    if not os.path.exists(file):
        raise IOError("Failed to read file: %s!" % file)

    with open(file, "r") as file:
        data = file.read()
        file.close()

    # TODO: this is currently broken within panda!
    #if vfs.exists(file):
    #    data = vfs.readFile(file, 1)
    #elif mf is not None:  # We're reading from a multifile
    #    fileId = mf.findSubfile(file)
    #    data = mf.readSubfile(fileId)
    return data


def readPhysicsEntityFile(file):
    global physicsEntityFileCache
    if file in physicsEntityFileCache:
        data = physicsEntityFileCache[file]
    else:
        data = readFile("maps/" + file)
    physicsEntityFileCache[file] = data
    return data

class MapFile:

    def __init__(self):
        self.data = ""

    def write(self, line):
        self.data += line

class Map(DirectObject):
    """A Map loads all environment resources from a map file.
    Maps also keep track of the custom lights, skybox textures, sounds, etc, and can save this data back to a map file."""

    def __init__(self):
        global map
        map = self
        self.skyBox = None
        self.skyBoxFilename = ""
        self.sceneries = dict()
        self.staticGeometries = dict()
        self.worldSize = 0
        self.lights = []
        self.waterNode = None
        self.waterPlane = None
        self.waterPlaneNode = None
        self.waterPlaneNodePath = None
        self.mapDirectory = "maps"
        self.isSurvival = False
        self.ambientSound = None
        self.platforms = []
        self.name = ""

    def addSoundGroup(self, soundGroup):
        self.soundGroups[soundGroup.name] = soundGroup

    def addStaticGeometry(self, geom):
        if geom.node not in self.staticGeometries:
            self.staticGeometries[geom.node] = geom

    def deleteStaticGeometry(self, geom):
        geom.node.removeNode()
        geom.geometry.destroy()
        if geom.node in self.staticGeometries:
            del self.staticGeometries[geom.node]

    def showPlatforms(self):
        for p in self.platforms:
            p.show()

    def hidePlatforms(self):
        for p in self.platforms:
            p.hide()

    def disableShadows(self):
        for light in self.lights:
            if isinstance(
                    light.getNode(0),
                    Spotlight) and light.node().isShadowCaster():
                light.node().setShadowCaster(False)

    def enableShadows(self):
        for light in self.lights:
            if light.getTag("shadow") == "true":
                light.node().setShadowCaster(True, shadowMapWidth, shadowMapHeight)

    def load(self, name, aiWorld, entityGroup):
        "Loads the specified map file, creating all resources, and filling out the AI world and entity group."
        global cubeMap
        global reflectionEffectsNeeded

        self.name = name
        self.filename = "maps/" + self.name + ".txt"
        mapDirectory = "maps"

        data = readFile(self.filename)
        lines = data.split("\n")

        for line in lines:
            tokens = line.split()
            if len(tokens) == 0 or line[0] == "#":
                continue
            if tokens[0] == "world":
                self.worldSize = float(tokens[1])
            elif tokens[0] == "teams":
                numTeams = sum([int(token) for token in tokens[1:]])
                if net.netMode == constants.MODE_SERVER:
                    if len(tokens) > 2:  # 2v2
                        colors = [
                            Vec4(
                                0.7, 0.0, 0.0, 1), Vec4(
                                0.0, 0.0, 0.7, 1), Vec4(
                                0.2, 0.0, 0.0, 1), Vec4(
                                0.0, 0.0, 0.2, 1)]
                    else:  # Free-for-all up to 4 players
                        colors = [
                            Vec4(
                                0.5, 0.0, 0.0, 1), Vec4(
                                0.0, 0.0, 0.5, 1), Vec4(
                                0, 0.5, 0, 1), Vec4(
                                0.5, 0.5, 0, 1)]
                    for i in range(numTeams):
                        team = entities.TeamEntity()
                        team.color = colors[i]
                        docks = [x for x in aiWorld.docks if x.teamIndex == i]
                        if len(docks) > 0:
                            team.setDock(docks[0])
                        entityGroup.spawnEntity(team)
                        entityGroup.addTeam(team)
                    if len(tokens) > 2:  # x vs. y
                        # Set up allies. First team is allied with even teams,
                        # second team with odd.
                        i = 2
                        while i < len(entityGroup.teams):
                            entityGroup.teams[0].addAlly(
                                entityGroup.teams[i].getId())
                            i += 2
                        i = 3
                        while i < len(entityGroup.teams):
                            entityGroup.teams[1].addAlly(
                                entityGroup.teams[i].getId())
                            i += 2
            elif tokens[0] == "navmesh":
                aiWorld.navMesh = ai.NavMesh(mapDirectory, tokens[1])
            elif tokens[0] == "survival":
                self.isSurvival = True
                numTeams = 4
                if net.netMode == constants.MODE_SERVER:
                    colors = [
                        Vec4(
                            0.4, 0.0, 0.0, 1), Vec4(
                            0.0, 0.0, 0.4, 1), Vec4(
                            0, 0.4, 0, 1), Vec4(
                            0.4, 0.4, 0, 1)]
                    for i in range(4):
                        team = entities.TeamEntity()
                        team.money = 300  # Starting money amount for survival
                        team.color = colors[i]
                        team.isSurvivors = True
                        entityGroup.spawnEntity(team)
                        entityGroup.addTeam(team)
                    for team in entityGroup.teams:
                        for team2 in entityGroup.teams:
                            team.addAlly(team2.getId())
            elif tokens[0] == "glass":
                if net.netMode == constants.MODE_SERVER:
                    # Glass pane
                    glass = entities.Glass(aiWorld.world, aiWorld.space)
                    glass.initGlass(aiWorld.world, aiWorld.space,
                                    float(tokens[1]), float(tokens[2]))
                    glass.setPosition(
                        Vec3(
                            float(
                                tokens[3]), float(
                                tokens[4]), float(
                                tokens[5])))
                    glass.setPosition(glass.getPosition())
                    glass.setRotation(
                        Vec3(
                            float(
                                tokens[6]), float(
                                tokens[7]), float(
                                tokens[8])))
                    entityGroup.spawnEntity(glass)
            elif tokens[0] == "water":
                # Enable reflection rendering
                reflectionEffectsNeeded = True
                distortionEffectsChanged()

                maker = CardMaker("waterNode")
                maker.setFrame(-self.worldSize, self.worldSize, -
                               self.worldSize, self.worldSize)
                self.waterNode = render.attachNewNode(maker.generate())
                self.waterNode.setHpr(0, -90, 0)
                # Second token is water height
                self.waterNode.setPos(0, 0, float(tokens[1]))
                self.waterNode.setShader(loader.loadShader("images/water.sha"))
                self.waterNode.setTransparency(TransparencyAttrib.MAlpha)
                self.waterNode.setShaderInput(
                    "watermap", loader.loadTexture("images/water-normal.jpg"))
                self.waterNode.setShaderInput("time", clock.time)
                self.waterNode.hide(BitMask32.bit(4))
                self.waterPlane = Plane(
                    Vec3(0, 0, 1), Point3(0, 0, float(tokens[1])))
                self.waterPlaneNode = PlaneNode("waterPlaneNode")
                self.waterPlaneNode.setPlane(self.waterPlane)
                self.waterPlaneNodePath = render.attachNewNode(
                    self.waterPlaneNode)
                self.waterPlaneNodePath.hide()
                clipPlaneAttrib = ClipPlaneAttrib.make()
                clipPlaneAttrib = clipPlaneAttrib.addOnPlane(
                    self.waterPlaneNodePath)
                if reflectionCamera is not None:
                    self.waterNode.setShaderInput(
                        "reflectionscreen", reflectionRenderTexture)
                    reflectionCamera.node().setInitialState(RenderState.make(
                        CullFaceAttrib.makeReverse(), clipPlaneAttrib))
            elif tokens[0] == "geometry":
                # Setup static geometry
                geom = StaticGeometry(aiWorld.space, mapDirectory, tokens[1])
                geom.setPosition(
                    Vec3(float(tokens[2]), float(tokens[3]), float(tokens[4])))
                geom.commitChanges()
                self.addStaticGeometry(geom)
            elif tokens[0] == "geometry-scenery":
                # Setup static geometry
                geom = StaticGeometry(aiWorld.space, mapDirectory, tokens[1])
                geom.setPosition(
                    Vec3(float(tokens[2]), float(tokens[3]), float(tokens[4])))
                geom.commitChanges()
                geom.node.show()
                self.addStaticGeometry(geom)
            elif tokens[0] == "skybox":
                if not isDaemon:
                    self.skyBox = loadModel("models/skyboxes/" + tokens[1])
                    self.skyBox.setScale(self.worldSize)
                    self.skyBoxCustomModel = True
                    self.skyBoxFilename = tokens[1]
                    self.skyBox.setPos(camera.getPos(render))
                    self.skyBox.setBin('background', 0)
                    self.skyBox.setDepthWrite(0)
                    self.skyBox.setDepthTest(0)
                    self.skyBox.setClipPlaneOff()
                    self.skyBox.setTwoSided(True)
                    self.skyBox.setShaderOff()
                    self.skyBox.reparentTo(render)
            elif tokens[0] == "sound":
                if not isDaemon:
                    self.ambientSound = audio.FlatSound(
                        mapDirectory + "/" + tokens[1], float(tokens[2]))
                    self.ambientSound.setLoop(True)
                    self.ambientSound.play()
            elif tokens[0] == "light":
                if tokens[1] == "objects":
                    parentNode = renderObjects
                elif tokens[1] == "environment":
                    parentNode = renderEnvironment
                else:
                    parentNode = renderLit
                if tokens[2] == "directional":
                    light = DirectionalLight(tokens[3])
                    light.setSpecularColor(
                        Vec4(
                            float(
                                tokens[4]), float(
                                tokens[5]), float(
                                tokens[6]), 1))
                    light.setDirection(LVector3f(render.getRelativeVector(
                        lightNode, Vec3(0, 1, 0)) * -self.worldSize * 2.25))
                    light.setPoint(
                        Point3(
                            float(
                                tokens[7]), float(
                                tokens[8]), float(
                                tokens[9])))
                    lightNode = parentNode.attachNewNode(light)
                    # We can look this up later when we go to save, to
                    # differentiate between spotlights and directionals
                    lightNode.setTag("type", "directional")
                    if len(tokens) >= 11 and tokens[10] == "shadow" and hasattr(
                            light, "setShadowCaster"):
                        lightNode.setTag("shadow", "true")
                        if enableShadows:
                            light.setShadowCaster(
                                True, shadowMapWidth, shadowMapHeight)
                            light.setCameraMask(BitMask32.bit(4))
                    else:
                        lightNode.setTag("shadow", "false")
                    parentNode.setLight(lightNode)
                    self.lights.append(lightNode)
                elif tokens[2] == "ambient":
                    light = AmbientLight(tokens[3])
                    light.setColor(Vec4(float(tokens[4]), float(
                        tokens[5]), float(tokens[6]), 1))
                    lightNode = parentNode.attachNewNode(light)
                    parentNode.setLight(lightNode)
                    self.lights.append(lightNode)
                elif tokens[2] == "point":
                    light = PointLight(tokens[3])
                    light.setColor(Vec4(float(tokens[7]), float(
                        tokens[8]), float(tokens[9]), 1))
                    light.setAttenuation(
                        Vec3(
                            float(
                                tokens[10]), float(
                                tokens[11]), float(
                                tokens[12])))
                    lightNode = parentNode.attachNewNode(light)
                    lightNode.setPos(float(tokens[4]), float(
                        tokens[5]), float(tokens[6]))
                    parentNode.setLight(lightNode)
                    self.lights.append(lightNode)
                elif tokens[2] == "spot":
                    light = Spotlight(tokens[3])
                    lens = PerspectiveLens()
                    lens.setFov(float(tokens[16]))
                    light.setExponent(float(tokens[17]))
                    light.setLens(lens)
                    light.setColor(Vec4(float(tokens[10]), float(
                        tokens[11]), float(tokens[12]), 1))
                    light.setAttenuation(
                        Vec3(
                            float(
                                tokens[13]), float(
                                tokens[14]), float(
                                tokens[15])))
                    lightNode = parentNode.attachNewNode(light)
                    lightNode.setPos(float(tokens[4]), float(
                        tokens[5]), float(tokens[6]))
                    lightNode.setHpr(float(tokens[7]), float(
                        tokens[8]), float(tokens[9]))
                    if hasattr(light, "setShadowCaster") and len(
                            tokens) >= 19 and tokens[18] == "shadow":
                        light.setShadowCaster(True, 2048, 2048)
                        light.setCameraMask(BitMask32.bit(4))
                    parentNode.setLight(lightNode)
                    # We can look this up later when we go to save, to
                    # differentiate between spotlights and directionals
                    lightNode.setTag("type", "spot")
                    self.lights.append(lightNode)
            elif tokens[0] == "dock":
                dock = Dock(aiWorld.space, int(tokens[1]))
                pos = Vec3(float(tokens[2]), float(
                    tokens[3]), float(tokens[4]))
                dock.setPosition(pos)
                normal = Vec3(0, 0, 1)
                queue = aiWorld.getCollisionQueue(
                    Vec3(pos.getX(), pos.getY(), pos.getZ()), Vec3(0, 0, -1))
                for i in range(queue.getNumEntries()):
                    entry = queue.getEntry(i)
                    if entityGroup.getEntityFromEntry(entry) is not None:
                        continue
                    normal = entry.getSurfaceNormal(render)
                    break
                dock.setRotation(Vec3(0,
                                      math.degrees(-math.atan2(normal.getY(),
                                                               normal.getZ())),
                                      math.degrees(math.atan2(normal.getX(),
                                                              normal.getZ()))))
                aiWorld.docks.append(dock)
            elif tokens[0] == "physicsentity":
                if net.netMode == constants.MODE_SERVER:
                    file = tokens[1] + ".txt"
                    data = readPhysicsEntityFile(file)
                    parts = tokens[1].rpartition("/")
                    directory = mapDirectory + "/" + parts[0]
                    obj = entities.PhysicsEntity(
                        aiWorld.world, aiWorld.space, data, directory, tokens[1])
                    obj.setPosition(
                        Vec3(
                            float(
                                tokens[2]), float(
                                tokens[3]), float(
                                tokens[4])))
                    obj.setRotation(
                        Vec3(
                            float(
                                tokens[5]), float(
                                tokens[6]), float(
                                tokens[7])))
                    obj.controller.commitLastPosition()
                    entityGroup.spawnEntity(obj)
            elif tokens[0] == "spawnpoint":
                # Setup spawn point
                geom = SpawnPoint(aiWorld.space)
                geom.setPosition(
                    Vec3(float(tokens[1]), float(tokens[2]), float(tokens[3])))
                geom.setRotation(
                    Vec3(float(tokens[4]), float(tokens[5]), float(tokens[6])))
                aiWorld.spawnPoints.append(geom)
            elif tokens[0] == "scenery":
                scenery = loadModel(mapDirectory + "/" + tokens[1])
                scenery.setPos(float(tokens[2]), float(
                    tokens[3]), float(tokens[4]))
                scenery.reparentTo(renderLit)
                self.sceneries[tokens[1]] = scenery

        # Create winnar platforms
        entry = aiWorld.getFirstCollision(Vec3(0, 0, 100), Vec3(0, 0, -1))
        height = 15
        if entry is not None:
            height = entry.getSurfacePoint(render).getZ() + 10.0
        for i in range(numTeams):
            p = Platform(aiWorld.space)
            spacing = 7
            vspacing = 2
            offset = spacing / -2 if numTeams % 2 == 0 else 0
            p.setPosition(Vec3((math.ceil(i / 2.0) * (((i % 2) * 2) - 1) *
                                spacing) + offset, 0, height + (numTeams - 1 - i) * vspacing))
            p.commitChanges()
            p.hide()
            self.platforms.append(p)

    def save(self, aiWorld, entityGroup):
        "Saves a basic representation of the current game state (including environment resources) to a map file."
        mapFile = MapFile()
        mapFile.write("world " + str(self.worldSize) + "\n")
        if aiWorld.navMesh is not None:
            mapFile.write("navmesh " + aiWorld.navMesh.filename + "\n")
        index = 0
        for dock in aiWorld.docks:
            if dock.active:
                pos = dock.getPosition()
                mapFile.write("dock " +
                              str(index) +
                              " " +
                              str(pos.getX()) +
                              " " +
                              str(pos.getY()) +
                              " " +
                              str(pos.getZ()) +
                              "\n")
                index += 1
        if self.isSurvival:
            mapFile.write("survival\n")
        else:
            if len(entityGroup.teams[0].getAllies()) > 0:
                mapFile.write("teams " +
                              str(len(entityGroup.teams[0].getAllies()) +
                                  1) +
                              " " +
                              str(len(entityGroup.teams[1].getAllies()) +
                                  1) +
                              "\n")
            else:
                mapFile.write("teams " + str(len(entityGroup.teams)) + "\n")
        for geom in list(self.staticGeometries.values()):
            pos = geom.getPosition()
            keyword = "geometry"
            if not geom.node.isHidden():
                keyword = "geometry-scenery"
            mapFile.write(keyword +
                          " " +
                          geom.filename +
                          " " +
                          str(pos.getX()) +
                          " " +
                          str(pos.getY()) +
                          " " +
                          str(pos.getZ()) +
                          "\n")
        if self.skyBox is not None:
            mapFile.write("skybox " + self.skyBoxFilename + "\n")
        if self.ambientSound is not None:
            mapFile.write("sound " +
                          self.ambientSound.filename.replace(self.mapDirectory +
                                                             "/", "") +
                          " " +
                          str(self.ambientSound.getVolume()) +
                          "\n")
        if self.waterNode is not None:
            mapFile.write("water " + str(self.waterNode.getZ()) + "\n")
        for light in self.lights:
            color = light.getNode(0).getColor()
            mapFile.write("light ")
            if light.getNode(0).getParent(0) == renderObjects:
                mapFile.write("objects ")
            elif light.getNode(0).getParent(0) == renderEnvironment:
                mapFile.write("environment ")
            else:
                mapFile.write("all ")
            if isinstance(light.getNode(0), AmbientLight):
                mapFile.write("ambient " +
                              light.getName() +
                              " " +
                              str(color.getX()) +
                              " " +
                              str(color.getY()) +
                              " " +
                              str(color.getZ()) +
                              "\n")
            elif isinstance(light.getNode(0), Spotlight):
                # Could be a real spotlight, or it could be a directional
                # light, since we fake those.
                if light.getTag("type") == "directional":
                    mapFile.write("directional " +
                                  light.getName() +
                                  " " +
                                  str(color.getX()) +
                                  " " +
                                  str(color.getY()) +
                                  " " +
                                  str(color.getZ()) +
                                  " " +
                                  str(light.getH()) +
                                  " " +
                                  str(light.getP()) +
                                  " " +
                                  str(light.getR()) +
                                  (" shadow" if light.node().isShadowCaster() else "") +
                                  "\n")
                else:
                    pos = light.getPos(render)
                    atten = light.getNode(0).getAttenuation()
                    fov = light.getNode(0).getLens().getFov()
                    exponent = light.getNode(0).getExponent()
                    mapFile.write("spot " +
                                  light.getName() +
                                  " " +
                                  " " +
                                  str(pos.getX()) +
                                  " " +
                                  str(pos.getY()) +
                                  " " +
                                  str(pos.getZ()) +
                                  " " +
                                  str(light.getH()) +
                                  " " +
                                  str(light.getP()) +
                                  " " +
                                  str(light.getR()) +
                                  " " +
                                  str(color.getX()) +
                                  " " +
                                  str(color.getY()) +
                                  " " +
                                  str(color.getZ()) +
                                  " " +
                                  str(atten.getX()) +
                                  " " +
                                  str(atten.getY()) +
                                  " " +
                                  str(atten.getZ()) +
                                  " " +
                                  str(fov) +
                                  " " +
                                  str(exponent) +
                                  " " +
                                  (" shadow" if light.getTag("shadow") == "true" else "") +
                                  "\n")
            elif isinstance(light.getNode(0), PointLight):
                atten = light.getNode(0).getAttenuation()
                pos = light.getPos(render)
                mapFile.write("point " +
                              light.getName() +
                              " " +
                              str(pos.getX()) +
                              " " +
                              str(pos.getY()) +
                              " " +
                              str(pos.getZ()) +
                              " " +
                              str(color.getX()) +
                              " " +
                              str(color.getY()) +
                              " " +
                              str(color.getZ()) +
                              " " +
                              str(atten.getX()) +
                              " " +
                              str(atten.getY()) +
                              " " +
                              str(atten.getZ()) +
                              "\n")
        for sceneryFile in list(self.sceneries.keys()):
            pos = self.sceneries[sceneryFile].getPos(render)
            mapFile.write("scenery " + sceneryFile + " " + str(pos.getX()) +
                          " " + str(pos.getY()) + " " + str(pos.getZ()) + "\n")
        for obj in (
            entity for entity in list(entityGroup.entities.values()) if isinstance(
                entity,
                entities.PhysicsEntity)):
            pos = obj.getPosition()
            hpr = obj.node.getHpr()
            mapFile.write("physicsentity " +
                          obj.dataFile +
                          " " +
                          str(pos.getX()) +
                          " " +
                          str(pos.getY()) +
                          " " +
                          str(pos.getZ()) +
                          " " +
                          str(hpr.getX()) +
                          " " +
                          str(hpr.getY()) +
                          " " +
                          str(hpr.getZ()) +
                          "\n")
        for glass in (
            entity for entity in list(entityGroup.entities.values()) if isinstance(
                entity,
                entities.Glass)):
            pos = glass.getPosition()
            hpr = glass.getRotation()
            mapFile.write("glass " +
                          str(glass.glassWidth) +
                          " " +
                          str(glass.glassHeight) +
                          " " +
                          str(pos.getX()) +
                          " " +
                          str(pos.getY()) +
                          " " +
                          str(pos.getZ()) +
                          " " +
                          str(hpr.getX()) +
                          " " +
                          str(hpr.getY()) +
                          " " +
                          str(hpr.getZ()) +
                          "\n")
        for point in aiWorld.spawnPoints:
            if point.active:
                pos = point.getPosition()
                rot = point.getRotation()
                mapFile.write("spawnpoint " +
                              str(pos.getX()) +
                              " " +
                              str(pos.getY()) +
                              " " +
                              str(pos.getZ()) +
                              " " +
                              str(rot.getX()) +
                              " " +
                              str(rot.getY()) +
                              " " +
                              str(rot.getZ()) +
                              "\n")
        stream = open(self.filename, "w")
        stream.write(mapFile.data)
        stream.close()

    def update(self):
        "Updates the custom sounds and the skybox associated with this Map."
        if self.skyBox is not None:
            camPos = camera.getPos(render)
            self.skyBox.setPos(camPos - Vec3(0, 0, 25))
        if self.waterNode is not None:
            self.waterNode.setShaderInput("time", clock.time)
            if reflectionCamera is not None:
                reflectionCamera.setMat(
                    base.camera.getMat() * self.waterPlane.getReflectionMat())

    def delete(self):
        "Releases all resources, including scenery, physics geometries, and environment sounds and lights."
        global map
        map = None
        if self.skyBox is not None:
            self.skyBox.removeNode()
        for scenery in list(self.sceneries.values()):
            scenery.removeNode()
        self.sceneries.clear()
        for geom in list(self.staticGeometries.values()):
            self.deleteStaticGeometry(geom)
        self.staticGeometries.clear()
        for p in self.platforms:
            p.delete()
        del self.platforms[:]
        for light in self.lights:
            light.getParent().clearLight(light)
            light.removeNode()
        if self.waterNode is not None:
            self.waterNode.removeNode()
        del self.lights[:]
        if reflectionCamera is not None:
            reflectionCamera.node().setActive(False)
        if self.ambientSound is not None:
            self.ambientSound.stop()
            del self.ambientSound


class StaticGeometry(DirectObject):
    "A StaticGeometry is a potentially invisible, immovable physics object, modeled as a trimesh."

    def __init__(self, space, directory, filename=None):
        assert filename is not None
        self.filename = filename
        self.node = loadModel(directory + "/" + self.filename)
        self.node.reparentTo(renderEnvironment)
        self.node.hide()
        self.node.setCollideMask(BitMask32(1))
        triMeshData = OdeTriMeshData(self.node, True)
        self.geometry = OdeTriMeshGeom(space, triMeshData)
        self.geometry.setCollideBits(BitMask32(0x00000001))
        self.geometry.setCategoryBits(BitMask32(0x00000001))
        space.setSurfaceType(self.geometry, 0)

    def setPosition(self, pos):
        self.geometry.setPosition(pos)
        self.node.setPos(pos)

    def getPosition(self):
        return self.geometry.getPosition()

    def setRotation(self, hpr):
        self.node.setHpr(hpr)
        self.geometry.setQuat(self.node.getQuat(render))

    def getRotation(self):
        return self.node.getHpr()

    def commitChanges(self):
        "Updates the NodePath to reflect the position of the ODE geometry."
        self.node.setPosQuat(renderEnvironment, self.getPosition(), Quat(
            self.geometry.getQuaternion()))


class SpawnPoint(DirectObject):
    "Marks a location for units to spawn."

    def __init__(self, space):
        self.node = loadModel("models/spawnpoint/SpawnPoint")
        self.node.reparentTo(renderEnvironment)
        self.active = True

    def setPosition(self, pos):
        self.node.setPos(pos)

    def getPosition(self):
        return self.node.getPos()

    def setRotation(self, hpr):
        self.node.setHpr(hpr)

    def getRotation(self):
        return self.node.getHpr()

    def delete(self):
        self.active = False
        deleteModel(self.node, "models/spawnpoint/SpawnPoint")


class Dock(SpawnPoint):
    "Docks have a one-to-one relationship with Teams. Their Controllers increment the team's money and spawn newly purchased units."

    def __init__(self, space, teamIndex):
        self.teamIndex = teamIndex
        self.active = True
        self.radius = 6
        self.vradius = 2
        self.node = loadModel("models/dock/Dock")
        self.node.reparentTo(renderEnvironment)
        self.shieldNode = loadModel("models/shield/shield")
        self.shieldNode.reparentTo(self.node)
        self.shieldNode.setScale(self.radius)
        self.shieldNode.setTwoSided(True)
        self.shieldNode.setShaderOff(True)
        self.shieldNode.setColor(0.8, 0.9, 1.0, 0.6)
        self.shieldNode.setTransparency(TransparencyAttrib.MAlpha)
        self.shieldNode.hide(BitMask32.bit(4))  # Don't cast shadows

    def setPosition(self, pos):
        self.node.setPos(pos - Vec3(0, 0, self.vradius))

    def getPosition(self):
        return self.node.getPos() + Vec3(0, 0, self.vradius)


class Platform(DirectObject):
    "Makes a platform upon which to parade the game winners."

    def __init__(self, space):
        self.node = loadModel("maps/platform")
        self.node.reparentTo(renderEnvironment)
        self.collisionNode = CollisionNode("cnode")
        self.collisionNode.addSolid(CollisionSphere(0, 0, 0, 5))
        self.collisionNodePath = self.node.attachNewNode(self.collisionNode)
        self.collisionNode.setCollideMask(BitMask32(1))
        odeCollisionNode = loadModel("maps/platform-geometry")
        triMeshData = OdeTriMeshData(odeCollisionNode, True)
        self.geometry = OdeTriMeshGeom(space, triMeshData)
        self.geometry.setCollideBits(BitMask32(0x00000001))
        self.geometry.setCategoryBits(BitMask32(0x00000001))
        space.setSurfaceType(self.geometry, 0)

    def setPosition(self, pos):
        self.geometry.setPosition(pos)
        self.node.setPos(pos)

    def getPosition(self):
        return self.geometry.getPosition()

    def setRotation(self, hpr):
        self.node.setHpr(hpr)
        self.geometry.setQuaternion(self.node.getQuat(render))

    def getRotation(self):
        return self.node.getHpr()

    def show(self):
        self.geometry.enable()
        self.node.reparentTo(renderEnvironment)

    def hide(self):
        self.geometry.disable()
        self.node.reparentTo(hidden)

    def delete(self):
        deleteModel(self.node, "models/spawnpoint/SpawnPoint")
        self.geometry.destroy()

    def commitChanges(self):
        "Updates the NodePath to reflect the position of the ODE geometry."
        self.node.setPosQuat(renderEnvironment, self.getPosition(), Quat(
            self.geometry.getQuaternion()))


class Mouse:
    """A mouse can be created by any object that needs it (usually a controller).
    However, there should only be one mouse active at a time, since each Mouse object will recenter the cursor every frame."""
    enabled = True

    def __init__(self):
        base.disableMouse()
        self._lastX = base.win.getProperties().getXSize() / 2
        self._lastY = base.win.getProperties().getYSize() / 2
        self._x = 0
        self._y = 0
        self.baseSpeed = 0.001
        self.speed = 1
        self._dx = 0
        self._dy = 0
        self._maxY = math.pi * 0.5
        self._minY = -self._maxY
        self.lastUpdate = 0

    def setYLimit(self, maxY, minY):
        self._maxY = maxY
        self._minY = minY

    def setSpeed(self, speed):
        "Sets the sensitivity of the mouse."
        self.speed = speed

    def update(self):
        "Updates the mouse's position and speed, then recenters the cursor in the window."
        if not Mouse.enabled:
            return
        self.lastUpdate = clock.time
        pointer = base.win.getPointer(0)
        mouseX = pointer.getX()
        mouseY = pointer.getY()
        self._dx = (mouseX - self._lastX) * self.baseSpeed * self.speed
        self._dy = -(mouseY - self._lastY) * self.baseSpeed * self.speed
        self._lastX = mouseX
        self._lastY = mouseY
        self._x += self._dx
        self._y = min(self._maxY, max(self._minY, self._y + self._dy))
        centerX = base.win.getProperties().getXSize() / 2
        centerY = base.win.getProperties().getYSize() / 2
        if base.win.movePointer(0, int(centerX), int(centerY)):
            self._lastX = centerX
            self._lastY = centerY

    def setX(self, x):
        self._x = x

    def setY(self, y):
        self._y = y

    def getX(self):
        return self._x

    def getDX(self):
        return self._dx

    def getDY(self):
        return self._dy

    def getY(self):
        return self._y

    @staticmethod
    def showCursor():
        Mouse.enabled = False
        props = WindowProperties()
        props.setMouseMode(WindowProperties.MAbsolute)
        props.setCursorHidden(False)
        base.win.requestProperties(props)

    @staticmethod
    def hideCursor():
        Mouse.enabled = True
        props = WindowProperties()
        props.setMouseMode(WindowProperties.MRelative)
        props.setCursorHidden(True)
        base.win.requestProperties(props)
        base.win.movePointer(0, int(base.win.getProperties().getXSize() / 2),
            int(base.win.getProperties().getYSize() / 2))


class Light(object):
    """
    At this time, only point lights are supported. Really though, what do you need a spotlight for?
    This class is necessary because every time a Panda3D light is added, all shaders must be regenerated.
    This class keeps a constant number of lights active at all times, but sets the unnecessary extra lights to have no effect.
    """

    def __init__(self, color, attenuation):
        self.color = Vec4(color)
        self.attenuation = Vec3(attenuation)
        self.position = Vec3(0, 0, 0)
        self.node = None

    def setPos(self, pos):
        self.position = Vec3(pos)
        if self.node is not None:
            self.node[1].setPos(self.position)

    def setColor(self, color):
        self.color = Vec4(color)
        if self.node is not None:
            self.node[1].setColor(self.color)

    def setAttenuation(self, attenuation):
        """
        Attenuation is a 3D vector containing quadratic, linear, and constant attenuation coefficients.
        """

        self.attenuation = Vec3(attenuation)
        if self.node is not None:
            self.node[0].setAttenuation(self.attenuation)

    def add(self):
        """
        Adds this light to the active light list, basically enabling it.
        """

        if self not in lights:
            lights.append(self)
            if len(lights) <= len(lightNodes) and self.node is None:
                self.node = lightNodes[len(lights) - 1]
                self.node[1].setPos(self.position)
                self.node[0].setSpecularColor(self.color)
                self.node[0].setAttenuation(self.attenuation)

    def remove(self):
        """
        Removes this light from the active light list, disabling it.
        """

        if self in lights:
            lights.remove(self)

        if self.node is not None:
            self.node[0].setSpecularColor(Vec4(0, 0, 0, 1))
            self.node[0].setAttenuation(Vec3(0, 0, 1))

        self.node = None


def impulseToForce(fx, fy=None, fz=None):
    "Converts an impulse to a force (either a vector or a scalar) by dividing by the timestep of the last ODE frame."
    if fy is not None and fz is not None:
        force = Vec3(fx, fy, fz)
        return force / clock.timeStep
    else:
        return fx / clock.timeStep


def frange(start, end=None, inc=None):
    "A range function that accepts float increments."
    if end is None:
        end = start + 0.0
        start = 0.0
    else:
        start += 0.0  # force it to be a float

    if inc is None:
        inc = 1.0
    count = int(math.ceil((end - start) / inc))

    L = [None, ] * count

    L[0] = start
    for i in range(1, count):
        L[i] = L[i - 1] + inc
    return L


def lerp(a, b, scale):
    "Interpolate between two Vec3's, based on the 'scale' parameter, where 'scale' goes from 0 to 1."
    return a + ((b - a) * scale)
