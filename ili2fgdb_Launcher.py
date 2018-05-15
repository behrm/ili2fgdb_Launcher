# -*- coding: iso-8859-15 -*-
'''
Created on 11.08.2017

@author: Bernhard Ehrminger
'''
import atexit
import glob
import inspect
import logging
import os
import shutil
import subprocess
import tempfile
from zipfile import ZipFile

import pathlib2


class ili2fgdb_Launcher(object):
    '''
    classdocs
    '''

    # define 2 class-attributes with error handling
    try:
        proxy = os.environ['HTTP_PROXY'].rsplit(':', 1)[0].replace('http://', '')
        proxyPort = os.environ['HTTP_PROXY'].rsplit(':', 1)[1]
    except Exception as e:
        print('leider entsteht ein Fehler beim Auswerten der Umgebungsvariablen "HTTP_PROXY"')
        raise e

    java_exe_64bit = r'C:\ProgramData\Oracle\Java\javapath\java.exe'
    if not os.path.exists(java_exe_64bit):
            raise Exception('die Java Installation {0} wurde nicht gefunden'.format(java_exe_64bit))
    

    def __init__(self, zipArchiv='ili2fgdb-3.11.3.zip', logger=None):        
        '''
        Geloggt wird nur, wenn ein Logger übergeben wird.
        Optinal können andere Versionen, als die der Deafult-Parametriesierung, angesteurt werden.
        '''
        
        if not logger is None:
            self.logger = logger

        self.zipArchiv = os.path.dirname(inspect.getsourcefile(type(self))) + os.sep + zipArchiv

        # Das auszupackende Zip-Archiv muss mit diesem Module im gleichen Verzeichnis liegen!

        if not pathlib2.Path(self.zipArchiv).is_file():
            raise IOError('Zip-Archiv{0} not found'.format(self.zipArchiv))
        
        # Temp-Verzeichnisse mit zufällig generierten Namen ermöglichen multiprocessing mit dieser Klasse
        self.temporaryDirectory = tempfile.mkdtemp()
        if hasattr(self, 'logger'):
            self.logger.debug('Unzip Archive {0} to {1}'.format(self.zipArchiv, self.temporaryDirectory))
        with ZipFile(self.zipArchiv, 'r') as myzip:
            for name in myzip.namelist():
                myzip.extract(name, self.temporaryDirectory)

        self.java_jar_File = glob.glob(self.temporaryDirectory + os.sep + r'*\ili2fgdb.jar')[0]

        if not os.path.exists(self.java_jar_File):
            raise IOError("Das Java-Archiv 'ili2fgdb.jar' konnte innerhalb {0} nicht gefunden werden".format(self.zipArchiv))
        atexit.register(self.cleanUp)
        return
    
    
    def __enter__(self):
        return self
    
    def __exit__(self, ext_type, exc_value, traceback):
        # contextmanager räumt auf
        if os.path.exists(self.temporaryDirectory):
            shutil.rmtree(self.temporaryDirectory)


    def cleanUp(self):
        # aufräumen ohne contextmanager beim programmende
        if os.path.exists(self.temporaryDirectory):
            shutil.rmtree(self.temporaryDirectory)

    def __get_default_schema_params(self, smart2Inheritance, smart1Inheritance, noSmartMapping):
        '''
        Es soll immer NUR ein Modell zur Abbildung der Vererbung ausgewählt werden.
        Ohne explizite Auswahl beim Aufruf wird "smart2Inheritance" eingesetzt.
        '''
        if [smart2Inheritance, smart1Inheritance, noSmartMapping].count(True) == 0:
            # ohne benutzerauswahl: aufruf mit impliziten default parameter
            return ['--smart2Inheritance']
        
        elif (not [smart2Inheritance,
                   smart1Inheritance,
                   noSmartMapping].count(True) == 1):
            # fehlerhafter aufruf mit 2 oder 3 True's oder sonstigem Gemüse
            raise Exception(''.join('''Es kann nur einer der Aufrufparameter 
                            smart1Inheritance, smart2Inheritance oder 
                            noSmartMapping mit True initialisiert werden''').split())
        else:
            # aufruf mit einem explizit angegebenen gültigen True
            if smart2Inheritance:
                return ['--smart2Inheritance']
            if smart1Inheritance:
                return ['--smart1Inheritance']
            if noSmartMapping:
                return ['--noSmartMapping']
        return  # should never run into

    def __jarWrapper(self, *args):
        '''
        Diese Methode baut die Dosbox-Comandline auf und 
        führt den Aufruf der 64bit Java Virtual Machine aus.
        '''
        command = [ili2fgdb_Launcher.java_exe_64bit, '-d64', '-jar', self.java_jar_File] + list(args)
        if hasattr(self, 'logger'):
            self.logger.info('Executing {0}'.format(' '.join(command)))

        filename = os.path.dirname(os.path.realpath(
            [x for x in args if x.endswith('.gdb')][0])) + os.sep + 'ili2fgdb_commandLine.log'
        with open(filename, 'w') as outfile:
            outfile.write(' '.join(command))
            outfile.flush()
        if hasattr(self, 'logger'):
            self.logger.debug('comandline: ' + ' '.join(command))
        try:
            # Ausführung ohne Fehler retourniert den Screen Output des Java-Programms
            return subprocess.check_output(command,
                                           stderr=subprocess.STDOUT,
                                           env=os.environ.copy())
        except subprocess.CalledProcessError as e:
            ''' alle fachlich/technischen Fehler (wegen ggf. aktivierter 
                Schema/Geometry Validierung ebenso wie Java Runtime Errors = Absturz 
                von Java wegen Programmfehler) gehen hier durch '''
            error_msg = 'Fehler in der Ausführung von {0}\nili2fgdb output:\n{1}\n\nReturn Code: {2}'.format(' '.join(command),
                                                                                                             str(e.output),
                                                                                                             e.returncode)
            if hasattr(self, 'logger'):
                self.logger.error(error_msg)
            raise Exception(error_msg)
        return  # should never run into

    def schema_import(self, fgdb_file='',
                      ili_model_from_file='',
                      modeldir='',
                      models='',
                      createBasketCol=False,
                      createEnumTxtCol=False,
                      defaultSrsAuth='EPSG',
                      defaultSrsCode=2056,
                      fgdbXyResolution=0.0001,  # defaults von arcpy.SpatialReference(2056)
                      fgdbXyTolerance=0.001,  # defaults von arcpy.SpatialReference(2056)
                      smart2Inheritance=False,
                      smart1Inheritance=False,
                      noSmartMapping=False,
                      createEnumTabs=True,
                      beautifyEnumDispName=True,
                      sqlEnableNull=True,
                      logFile=''):
        '''
        Erzeugt eine Filegeodatabase mit einem dem Interlis-Model entsprechenden Datenschema
        Die zur Abbildung des Datenmodells angelegten Tabellen sind leer.
        Bestimmte technische Tabellen haben bereits Inhalt. 
        Dieser Inhalt sollte in der Regel mit arcpy/FME etc. nicht manipuliert werden.
        Die Benennung der Aufrufparameter entspricht den comandline switches von ili2fgdb.
        Die Beschreibung der Funktion der Aufrufparameter findet sich in der Dokumentation 
        von ili2fgdb  


         :Aufrufparameter:

            :param fgdb_file:
            :param ili_model_from_file: 
            :param modeldir:
            :param models:
            :param createBasketCol:
            :param createEnumTxtCol:
            :param defaultSrsAuth:
            :param defaultSrsCode:
            :param fgdbXyResolution:
            :param fgdbXyTolerance:
            :param smart2Inheritance:
            :param smart1Inheritance:
            :param noSmartMapping:
            :param createEnumTabs:
            :param beautifyEnumDispName:
            :param sqlEnableNull:
            :param logFile:

        :Rückgabewert: 
            screenOutput: String - Ausführung ohne Fehler retourniert den Screen Output des Java-Programms ili2fgdb


        :Exceptions:
            bei fachlich/technischen Fehlern (wegen ggf. aktivierter Schema/Geometry Validierung ebenso 
            wie Java Runtime Errors = Absturz von Java wegen Programmfehler) wird eine Exception geworfen.
            Das Attribute 'message' der Exception enthält den Screen Output des Java-Programms ili2fgdb
        '''

        if len(fgdb_file) == 0:
            raise Exception('Name und Pfad zur neuen FGBD muss angegeben sein!')
        if pathlib2.Path(fgdb_file).is_dir():
            raise Exception('Die zu erzeugende FGBD {0} besteht bereits!'.format(fgdb_file))
        if not fgdb_file.endswith('.gdb'):
            raise Exception('Die zu erzeugende FGBD {0} endet nicht mit ".gdb"'.format(fgdb_file))

        if len(ili_model_from_file) == 0 and len(modeldir) == 0:
            raise Exception('Name und Pfad zur Datei mit dem Interlis-Modell muss angegeben sein!')

        args = ['--trace'] if hasattr(self, 'logger') and self.logger.isEnabledFor(logging.DEBUG) else []
        args += ['--schemaimport',
                 '--proxy', ili2fgdb_Launcher.proxy,
                 '--proxyPort', ili2fgdb_Launcher.proxyPort,
                 '--defaultSrsAuth', defaultSrsAuth.upper(),
                 '--defaultSrsCode', str(defaultSrsCode),
                 '--fgdbXyResolution', str(fgdbXyResolution),
                 '--fgdbXyTolerance', str(fgdbXyTolerance),
                 '--dbfile', fgdb_file]
        args += ['--log', str(logFile)] if len(str(logFile)) > 0 else []
        args += ['--createBasketCol'] if createBasketCol else []
        args += ['--createEnumTxtCol'] if createEnumTxtCol else []
        args += self.__get_default_schema_params(smart2Inheritance, smart1Inheritance, noSmartMapping)
        args += ['--createEnumTabs'] if createEnumTabs else []
        args += ['--beautifyEnumDispName'] if beautifyEnumDispName else []
        args += ['--sqlEnableNull'] if sqlEnableNull else []
        args += ['--models', str(models), '--modeldir', str(modeldir)] if len(modeldir) > 0 and len(models) > 0 else[]
        args += ['--log', str(logFile)] if len(str(logFile)) > 0 else []
        args += [ili_model_from_file] if len(ili_model_from_file) > 0 else []

        try:
            return self.__jarWrapper(*args)
        except Exception as e:
            raise e
        return

    def ili_import(self,
                   fgdb_file='',
                   transfer_file='',
                   modeldir='',
                   models='',
                   dataset='',
                   deleteData=False,
                   topics='',
                   createEnumTxtCol=False,
                   createBasketCol=False,
                   importTid=False,
                   defaultSrsAuth='epsg',
                   defaultSrsCode=2056,
                   fgdbXyResolution=0.0001,  # defaults von arcpy.SpatialReference(2056)
                   fgdbXyTolerance=0.001,  # defaults von arcpy.SpatialReference(2056)
                   disableValidation=False,
                   disableAreaValidation=False,
                   smart2Inheritance=False,
                   smart1Inheritance=False,
                   noSmartMapping=False,
                   createEnumTabs=True,
                   beautifyEnumDispName=True,
                   sqlEnableNull=True,
                   replace=False,
                   logFile=''):
        '''
        Erzeugt und befüllt eine leere Filegeodatabase mit Daten aus einem Interlis-Transfer File 


        Die Benennung der Aufrufparameter entspricht den comandline switches von ili2fgdb.
        Die Beschreibung der Funktion der Aufrufparameter findet sich in der Dokumentation 
        von ili2fgdb          

        :param fgdb_file:
        :param transfer_file:
        :param modeldir:
        :param models:
        :param dataset:
        :param deleteData:
        :param topics:
        :param createEnumTxtCol:
        :param createBasketCol:
        :param importTid:
        :param defaultSrsAuth:
        :param defaultSrsCode:
        :param fgdbXyResolution:
        :param fgdbXyTolerance:
        :param disableValidation:
        :param disableAreaValidation:
        :param smart2Inheritance:
        :param smart1Inheritance:
        :param noSmartMapping:
        :param createEnumTabs:
        :param beautifyEnumDispName:
        :param sqlEnableNull:
        :param replace:
        :param logFile:


        :Rückgabewert: 
            - screenOutput: String - Ausführung ohne Fehler retourniert den Screen Output des Java-Programms ili2fgdb

        :Exceptions:
            bei fachlich/technischen Fehlern (wegen ggf. aktivierter Schema/Geometry Validierung ebenso 
            wie Java Runtime Errors = Absturz von Java wegen Programmfehler) wird eine Exception geworfen.
            Das Attribute 'message' der Exception enthält den Screen Output des Java-Programms ili2fgdb
        '''

        if len(fgdb_file) == 0:
            raise Exception('Name und Pfad zur neuen FGBD muss angegeben sein!')
        if len(transfer_file) == 0:
            raise Exception('Name und Pfad zur Interlis- Transferdatei muss angegeben sein!')

        ''' Bezgsquelle ili-Model mit http-proxy ist in Tabelle T_ILI2DB_SETTINGS enthalten'''
        args = ['--trace'] if hasattr(self, 'logger') and self.logger.isEnabledFor(logging.DEBUG) else []
        args += ['--import']
        args += ['--dbfile', fgdb_file]
        args += ['--models', str(models)] if len(str(models)) > 0 else[]
        args += ['--proxy', ili2fgdb_Launcher.proxy,
                 '--proxyPort', ili2fgdb_Launcher.proxyPort,
                 '--defaultSrsAuth', defaultSrsAuth.upper(),
                 '--defaultSrsCode', str(defaultSrsCode),
                 '--fgdbXyResolution', str(fgdbXyResolution),
                 '--fgdbXyTolerance', str(fgdbXyTolerance)]
        args += ['--modeldir', str(modeldir)]if len(str(modeldir)) > 0 else[]
        args += ['--dataset', str(dataset)] if len(str(dataset)) > 0 else[]
        args += ['--disableValidation'] if disableValidation else []
        args += ['--disableAreaValidation'] if disableAreaValidation else []
        args += ['--deleteData'] if deleteData else []
        args += ['--topics', str(topics)] if len(str(topics)) > 0 else []
        args += ['--importTid'] if importTid else []
        args += ['--createBasketCol'] if createBasketCol else []
        args += ['--createEnumTxtCol'] if createEnumTxtCol else []
        args += self.__get_default_schema_params(smart2Inheritance, smart1Inheritance, noSmartMapping)
        args += ['--createEnumTabs'] if createEnumTabs else []
        args += ['--beautifyEnumDispName'] if beautifyEnumDispName else []
        args += ['--sqlEnableNull'] if sqlEnableNull else []
        args += ['--replace'] if replace else []
        args += ['--log', str(logFile)] if len(str(logFile)) > 0 else []
        args += [transfer_file]

        try:
            return self.__jarWrapper(*args)
        except Exception as e:
            raise e
        return

    def ili_export(self,
                   fgdb_file='',
                   transfer_file='',
                   models='',
                   modeldir='',
                   baskets='',
                   topics='',
                   defaultSrsAuth='epsg',
                   defaultSrsCode=2056,
                   disableValidation=False,
                   disableAreaValidation=False,
                   sqlEnableNull=True,
                   logFile=''):

        args = ['--trace'] if hasattr(self, 'logger') and self.logger.isEnabledFor(logging.DEBUG) else []
        args += ['--export']
        args += ['--topics', topics] if topics else []
        args += ['--baskets'] if baskets else []
        args += ['--dbfile', fgdb_file,
                 '--models', models,
                 '--proxy', ili2fgdb_Launcher.proxy,
                 '--proxyPort', ili2fgdb_Launcher.proxyPort]
        args += ['--modeldir', str(modeldir)]if len(str(modeldir)) > 0 else[]
        args += ['--sqlEnableNull'] if sqlEnableNull else []
        args += ['--disableValidation'] if disableValidation else []
        args += ['--disableAreaValidation'] if disableAreaValidation else []
        args += ['--log', str(logFile)] if len(str(logFile)) > 0 else []
        args += [transfer_file]

        try:
            return self.__jarWrapper(*args)
        except Exception as e:
            raise e
        return

    def ili_update(self,
                   fgdb_file='',
                   transfer_file='',
                   modeldir='',
                   models='',
                   dataset='',
                   deleteData=False,
                   topics='',
                   createEnumTxtCol=False,
                   createBasketCol=False,
                   importTid=False,
                   defaultSrsAuth='epsg',
                   defaultSrsCode=2056,
                   fgdbXyResolution=0.0001,  # defaults von arcpy.SpatialReference(2056)
                   fgdbXyTolerance=0.001,  # defaults von arcpy.SpatialReference(2056)
                   disableValidation=False,
                   disableAreaValidation=False,
                   sqlEnableNull=True,
                   smart2Inheritance=False,
                   smart1Inheritance=False,
                   noSmartMapping=False,
                   logFile=''):

        args = ['--trace'] if hasattr(self, 'logger') and self.logger.isEnabledFor(logging.DEBUG) else []
        args += ['--update',
                 '--proxy', ili2fgdb_Launcher.proxy,
                 '--proxyPort', ili2fgdb_Launcher.proxyPort,
                 '--defaultSrsAuth', defaultSrsAuth.upper(),
                 '--defaultSrsCode', str(defaultSrsCode),
                 '--fgdbXyResolution', str(fgdbXyResolution),
                 '--fgdbXyTolerance', str(fgdbXyTolerance)]

        args += ['--dataset', str(dataset)] if len(str(dataset)) > 0 else[]
        args += ['--disableValidation'] if disableValidation else []
        args += ['--disableAreaValidation'] if disableAreaValidation else []
        args += ['--sqlEnableNull'] if disableAreaValidation else []
        args += self.__get_default_schema_params(smart2Inheritance, smart1Inheritance, noSmartMapping)
        args += ['--deleteData'] if deleteData else []
        args += ['--topics', str(topics)] if len(str(topics)) > 0 else []
        args += ['--importTid'] if importTid else []
        args += ['--createBasketCol'] if createBasketCol else []
        args += ['--createEnumTxtCol'] if createEnumTxtCol else []
        args += ['--models', str(models)] if len(str(models)) > 0 else[]
        args += ['--modeldir', str(modeldir)]if len(str(modeldir)) > 0 else[]
        args += ['--log', str(logFile)] if len(str(logFile)) > 0 else []
        args += ['--dbfile', fgdb_file]
        
        args += [transfer_file]

        try:
            return self.__jarWrapper(*args)
        except Exception as e:
            raise e
        return
