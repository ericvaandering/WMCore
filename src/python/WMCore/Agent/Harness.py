#!/usr/bin/env python
"""
Harness class that wraps standard functionality used in all deamon 
components including:

(1) Instantiating message service, trigger and other database classes
including session objects and workflow entities.

(2) Subscribing to default messages (e.g. logging and stopping server)

(3) Providing a method to test the component without a message service

(4) Instatiate the log master

(5) Provides basic uniform log information (useful for operators)

(6) Method to publish monitoring information

"""

__revision__ = "$Id: Harness.py,v 1.5 2008/09/16 15:03:03 fvlingen Exp $"
__version__ = "$Revision: 1.5 $"
__author__ = "fvlingen@caltech.edu"

from logging.handlers import RotatingFileHandler

import logging
import os
import threading


from WMCore.Database.DBFactory import DBFactory
from WMCore.Database.Transaction import Transaction
from WMCore.WMException import WMException
from WMCore.WMExceptions import WMEXCEPTION
from WMCore.WMFactory import WMFactory

class Harness:
    """
    Harness class that wraps standard functionality used in all deamon 
    components
    """

    def __init__(self, config):
        """
        init
   
        The constructor is empty as we have an initalization method
        that can be called inside new threads (we use thread local attributes
        at startup.

        Default intialization of the harness including setting some diagnostic
        messages
        """
        self.config = config

    def initInThread(self):
        """
        Default intialization of the harness including setting some diagnostic
        messages. This method is called when we call 'prepareToStart'
        """
        try:
            self.state = 'startup'
            self.messages = {}
            # the component name is the last part of its module name
            # and it should override any name give through the arguments.
            compName = self.__class__.__name__
            if not compName in self.config.listComponents_():
                raise WMException(WMEXCEPTION['WMCORE-8']+compName, 'WMCORE-8')
            self.config.Agent.componentName = compName 
            compSect = getattr(self.config, compName, None) 
            compSect.componentDir =  os.path.join(self.config.General.workDir, \
                self.config.Agent.componentName)
            if not hasattr(compSect, "logFile"):
                compSect.logFile = os.path.join(compSect.componentDir,\
                    "ComponentLog")
            # we have name and location of the log files. Now make sure there
            # is a directory.
            try:
                os.makedirs(compSect.componentDir)
            except :
                print('component dir already exists. Continue on with initialization')
            logHandler = RotatingFileHandler(compSect.logFile,
                "a", 1000000, 3)
            logFormatter = \
                logging.Formatter("%(asctime)s:%(module)s:%(message)s")
            logHandler.setFormatter(logFormatter)
            logging.getLogger().addHandler(logHandler)
            logging.getLogger().setLevel(logging.INFO)
            if hasattr(compSect, "logLevel"):
                if compSect.logLevel == 'DEBUG':
                   logging.getLogger().setLevel(logging.DEBUG)
                elif compSect.logLevel == 'ERROR':
                   logging.getLogger().setLevel(logging.ERROR)
                elif compSect.logLevel == 'NOTSET':
                   logging.getLogger().setLevel(logging.NOTSET)
             
            logging.info(">>>Starting: "+compName+'<<<')
            # check which backend to use: MySQL, Oracle, etc... for core 
            # services.
            # we recognize there can be more than one database.
            # be we offer a default database that is used for core services.
            logging.info(">>>Initializing default database")
            logging.info(">>>Check if connection is through socket")
            myThread = threading.currentThread()
            myThread.logger = logging.getLogger()
            logging.info(">>>Setting config for thread: ")
            myThread.config = self.config
            options = {}
            coreSect = self.config.CoreDatabase
            if hasattr(coreSect, "socket"):
                options['unix_socket'] = coreSect.socket
            logging.info(">>>Building database connection string")
            dbStr = coreSect.dialect + '://' + coreSect.user + \
                ':' + coreSect.passwd+"@"+coreSect.hostname+'/'+\
                coreSect.name
            # we only want one DBFactory per database so we will need to 
            # to pass this on in case we are using threads.
            myThread.dbFactory = DBFactory(myThread.logger, dbStr, options)
            myThread.dbi = myThread.dbFactory.connect()

            logging.info(">>>Initialize transaction dictionary")
            if not hasattr(coreSect, "dialect"):
                raise WMException(WMEXCEPTION['WMCORE-5'],'WMCORE-5')
            logging.info(">>>Determining Dialect: "+coreSect.dialect)
            if coreSect.dialect == 'mysql':
                myThread.dialect = 'MySQL'
            logging.info(">>>Initializing MsgService Factory")
            WMFactory("msgService", "WMCore.MsgService."+ \
                myThread.dialect)
            myThread.msgService = \
                myThread.factory['msgService'].loadObject("MsgService")

            myThread.transactions = {}
            # diagnostic messages are ones that most of the time
            # bypass the other messages. 
            logging.info(">>>Initializing diagnostic messages")
            self.diagnosticMessages = []
            # can be used to print out the parameter 
            # and handlers used by an agent
            self.diagnosticMessages.append(compName + ':LogState')
            self.diagnosticMessages.append('LogState')
            # start/stop debug
            self.diagnosticMessages.append(compName + ':Logging.DEBUG')
            self.diagnosticMessages.append(compName + ':Logging.INFO')
            self.diagnosticMessages.append(compName + ':Logging.ERROR')
            self.diagnosticMessages.append(compName + ':Logging.NOTSET')
            self.diagnosticMessages.append('Logging.DEBUG')
            self.diagnosticMessages.append('Logging.INFO')
            self.diagnosticMessages.append('Logging.ERROR')
            self.diagnosticMessages.append('Logging.NOTSET')
            # events to stop the component.
            self.diagnosticMessages.append(compName + ':Stop')
            self.diagnosticMessages.append('Stop')

            logging.info(">>>Instantiating trigger service")
            WMFactory("trigger", "WMCore.Trigger")
            myThread.trigger = myThread.factory['trigger'].loadObject("Trigger")
            logging.info("Harness part constructor finished")
        except Exception,ex:
            logging.critical("Problem instantiating "+str(ex))
            raise

    def preInitialization(self):
        """
        _preInitialization_
 
        returns: nothing
        
        method that can be overloaded and will be called before the 
        start component is called. (enables you to set message->handler 
        mappings). You use the self.message dictionary of the base class
        to define the mappings.

        """
        pass

    def postInitialization(self):
        """
        _postInitialization_
 
        returns: nothing
        
        method that can be overloaded and will be called after the start 
        component does the standard initialization, but before the wait 
        (enables you to publish events when starting up)

        Define actions you want to execute before the actual message
        handling starts. E.g.: publishing some messages, or removing
        messages.

        """
        pass

    def logState(self):
        """
        _logState_
 
        returns: string
        
        method that can be overloaded to log additional state information 
        (should return atring)
        """
        msg = 'No additional state information for ' + \
            self.config.Agent.componentName
        return msg

    def publishItem(self, items = {}):
        """
        _publishItem_

        returns: nothing
  
        A method that publishes a (dictionary) set or 1 item
        to a monitoring service.
        """
        #FIXME: do we need this method. If so we need to agree
        #FIXME: on some default monitoring publication mechanism.
        pass

    def __call__(self, event, payload):
        """
        Loads the correct handler and performs the apropiate actions
        """
        compName = self.config.Agent.componentName
        # check if it is not a diagnostic event.
        if not event in self.diagnosticMessages:
            if not event in self.messages.keys():
                msg = """
Message %s with payload: %s has no handler in this component.
I am going to throw a fatal error! The following message subscriptions 
which have a handler, have been found: diagnostic: %s and component specific: %s 
                """ % (event, payload, str(self.diagnosticMessages), \
                str(self.messages.keys()))
                logging.critical(msg)
                raise Exception(msg)
            handler = self.messages[event]
            logging.debug("Retrieving Handler for event: "+event)
            logging.debug("Executing Payload " + str(payload))
            handler.__call__(event, payload)
            logging.debug("Event " + str(event) + " successfully handled")
        # diagnostics are tiny operations so we put them here rather 
        # than in separate handlers
        else:
            if(event == compName+':Logging.DEBUG') or \
                (event == 'Logging.DEBUG'):
                logging.getLogger().setLevel(logging.DEBUG)
                logging.info("Log level set to DEBUG")
            elif(event == compName+':Logging.INFO') or \
                (event == 'Logging.INFO'):
                logging.getLogger().setLevel(logging.INFO)
                logging.info("Log level set to INFO")
            elif(event == compName+':Logging.ERROR') or \
                (event == 'Logging.ERROR'):
                logging.getLogger().setLevel(logging.ERROR)
                logging.info("Log level set to ERROR")
            elif(event == compName+':Logging.NOTSET') or \
                (event == 'Logging.NOTSET'):
                logging.getLogger().setLevel(logging.NOTSET)
                logging.info("Log level set to ERROR")
            elif(event == compName+':LogState') or \
                (event == 'LogState'):
                logging.info(str(self))

    def initialization(self):
        """
        _initialization__

        Performs the basic initialization. e.g.:
        
        - registering the trigger and message service with handlers
        - checking if the component specific message types conflict
        with the default diagnostic ones
        - registering itself with the message service
        - subscribing to message types.
        """
 
        try:
  
            myThread = threading.currentThread()
            # register this component
            logging.info(">>>Registering this component to msgService")
            myThread.msgService.registerAs(self.config.Agent.componentName)
            logging.info(">>>Subscribing to events:")
            # subscribe to messages (or generate a warning:
            if len(self.messages.keys())==0:
                logging.warning("COMPONENT DOES NOT SUBSCRIBE TO MESSAGES!")
                logging.warning("IS THIS INTENTIONAL?!")
            for message in self.messages.keys():
                # check if the messages do not conflict with our 
                # diagnostic ones
                if message in self.diagnosticMessages:
                    raise WMException(WMEXCEPTION['WMCORE-6'], 'WMCORE-6')
                myThread.msgService.subscribeTo(message)
                logging.info(">>>Subscribed to event : " + message)
            logging.info(">>>Subscribing to diagnostic events : ")
            for message in self.diagnosticMessages:
                myThread.msgService.prioritySubscribeTo(message)
                logging.info(">>>Subscribed to event : " + message)
            # remove any stop messages that where send to us
            # while we where not running
            logging.info(">>>Before I start I purge any stop messages send "+\
                "to me")
            myThread.msgService.remove("Stop")
            myThread.msgService.remove(self.config.Agent.componentName+":Stop")
        except Exception,ex:
            logging.critical("Prolem initializing : "+str(ex))
            raise

    def prepareToStart(self):
        """
        _prepareToStart_

        returns: Nothing

        Starts the initialization procedure. It is mainly an aggregation method
        so it can easily used in tests.
        """
        self.state = 'initialize'
        self.initInThread()
        type = None
        payload = None
        # note: every component gets a (unique) name: 
        # self.config.Agent.componentName
        logging.info('>>>Starting initialization\n')

        logging.info('>>>Setting default transaction')
        myThread = threading.currentThread()
        myThread.transaction = Transaction(myThread.dbi)
        myThread.transaction.commit()

        self.preInitialization()
        myThread.transaction.begin()
        self.initialization()
        self.postInitialization()
        myThread.transaction.commit()

        logging.info('>>>Committing default transaction')
        logging.info(">>>Flushing messages")
        myThread.msgService.finish()

        logging.info('>>>Committing possible other transactions')
        # if we have multiple database we might want to synchronize
        # commits
        for transaction in myThread.transactions.keys():
            transaction.commit()

        logging.info(">>>Initialization finished!\n")    
        # wait for messages
        self.state = 'active'


    def handleMessage(self, type, payload):
        """
        __handleMessage_

        A direct method for handling events for this component.
        This method is mainly used for testing frameworks where you want to 
        have immediate feedback on the handling of a message in the test framework.
        """ 
        logging.debug("Receiving message of type: "+str(type)+\
        ", payload: "+str(payload))
         # check if it is a stop message:
        if type == 'Stop' or type == self.config.Agent.componentName+':Stop':
            return
        self.__call__(type, payload)

    def startComponent(self):
        """
        _startComponent_

        returns: Nothing

        Start up the component, performs initialization an waits 
        for messages.
 
        """
        myThread = threading.currentThread()
        try:
            msg = 'None'
            self.prepareToStart()
            while True:
                msg = myThread.msgService.get()
                # we commit here as we do not want long standing open 
                # database connections (but we keep track of the last get 
                # message state
                self.handleMessage(msg['name'], msg)
                logging.debug(">>>Closing and commit all database sessions" \
                    +" that have been registered")
                # when we call the msgService.finish we finally remove the msg
                # from the queu.
                myThread.msgService.finish()
                for transaction in myThread.transactions.keys():
                    transaction.commit()
                logging.debug(">>>Finished handling message of type "+ \
                    str(msg['name'])+ " \n")
                if msg['name'] == 'Stop' or msg['name'] == self.config.Agent.componentName+':Stop':
                    logging.info(">>>Gracefully shutting down component")
                    break
        except Exception,ex:
            logging.info(\
                ">>>Fatal error, rollback all non-committed transactions")
            logging.info(">>>Closing all connections")
            for transaction in myThread.transactions.keys():
                transaction.rollback()
            if self.state == 'initialize':
                msg = """ 
PostMortem: choked when initializing with error: %s
                """ % (str(ex))
            else:
                errormsg = """ 
PostMortem: choked while handling messages  with error: %s
while trying to handle msg: %s
                """ % (str(ex), str(msg))
            logging.critical(errormsg)
            raise
        logging.info("System shutdown complete!")

    def __str__(self):
        """

        return: string
 
        String representation of the status of this component.
        """
        
        msg = 'Status of this component : \n'
        msg += '\n'
        msg += '>>Event Subscriptions --> Handlers<<\n' 
        msg += '------------------------------------\n'
        for message in self.messages.keys():
            msg += message+'-->'+ str(self.messages[message])+'\n'
        msg += '\n'
        msg += '\n'
        msg += '>>Parameters --> Values<<\n'
        msg += '-------------------------\n'
        msg += str(self.config)
        additionalMsg = self.logState()
        if additionalMsg != '':
            msg += '\n'
            msg += 'Additional state information\n'
            msg += '----------------------------\n'
            msg += '\n'
            msg += str(additionalMsg)
            msg += '\n'
        return msg
   

