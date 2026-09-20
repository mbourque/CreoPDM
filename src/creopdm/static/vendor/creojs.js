var CreoJS = (function () {
    if (typeof Promise === 'undefined') {
        Promise = (function () {
            function NOOP() {}
    
            // States:
            var PENDING = 0;
            var FULFILLED = 1;
            var REJECTED = 2;
            var ADOPTED = 3;
    
            // to avoid using try/catch inside critical functions, we
            // extract them to here.
            var LAST_ERROR = null;
            var IS_ERROR = {};
    
            function getThen(obj) {
                try {
                    return obj.then;
                } catch (ex) {
                    LAST_ERROR = ex;
                    return IS_ERROR;
                }
            }
    
            function tryCallOne(fn, a) {
                try {
                    return fn(a);
                } catch (ex) {
                    LAST_ERROR = ex;
                    return IS_ERROR;
                }
            }
    
            function tryCallTwo(fn, a, b) {
                try {
                    fn(a, b);
                } catch (ex) {
                    LAST_ERROR = ex;
                    return IS_ERROR;
                }
            }
    
            function Promise(fn) {
                if (typeof this !== 'object') {
                    throw new TypeError('Promises must be constructed via new');
                }
                if (typeof fn !== 'function') {
                    throw new TypeError('Promise constructor\'s argument is not a function');
                }
                this._deferredState = PENDING;
                this._state = PENDING;
                this._value = null;
                this._deferreds = null;
                if (fn === NOOP) return;
                doResolve(fn, this);
            }
    
            Promise._onHandle = null;
            Promise._onReject = null;
            Promise._noop = NOOP;
    
            Promise.prototype.then = function(onFulfilled, onRejected) {
                if (this.constructor !== Promise) {
                    return safeThen(this, onFulfilled, onRejected);
                }
                var res = new Promise(NOOP);
                handle(this, new Handler(onFulfilled, onRejected, res));
                return res;
            };
    
            Promise.prototype.catch = function(onRejected) {
                return this.then (undefined, onRejected);
            };
    
            Promise.prototype.finally = function(handler) {
                return this.then (handler, handler);
            };
    
            function safeThen(self, onFulfilled, onRejected) {
                return new self.constructor(function (resolve, reject) {
                    var res = new Promise(NOOP);
                    res.then(resolve, reject);
                    handle(self, new Handler(onFulfilled, onRejected, res));
                });
            }
    
            function handle(self, deferred) {
                while (self._state === ADOPTED) {
                    self = self._value;
                }
                if (Promise._onHandle) {
                    Promise._onHandle(self);
                }
                if (self._state === PENDING) {
                    if (self._deferredState === PENDING) {
                        self._deferredState = FULFILLED;
                        self._deferreds = deferred;
                        return;
                    }
                    if (self._deferredState === FULFILLED) {
                        self._deferredState = REJECTED;
                        self._deferreds = [self._deferreds, deferred];
                        return;
                    }
                    self._deferreds.push(deferred);
                    return;
                }
                handleResolved(self, deferred);
            }
    
            function handleResolved(self, deferred) {
                setTimeout(function() {
                    var cb = self._state === FULFILLED ? deferred.onFulfilled : deferred.onRejected;
                    if (cb === null) {
                    if (self._state === FULFILLED) {
                        resolve(deferred.promise, self._value);
                    } else {
                        reject(deferred.promise, self._value);
                    }
                    return;
                    }
                    var ret = tryCallOne(cb, self._value);
                    if (ret === IS_ERROR) {
                        reject(deferred.promise, LAST_ERROR);
                    } else {
                        resolve(deferred.promise, ret);
                    }
                }, 0);
            }
    
            function resolve(self, newValue) {
                // Promise Resolution Procedure: https://github.com/promises-aplus/promises-spec#the-promise-resolution-procedure
                if (newValue === self) {
                    return reject(
                        self,
                        new TypeError('A promise cannot be resolved with itself.')
                    );
                }
                if (newValue && (typeof newValue === 'object' || typeof newValue === 'function')) {
                    var then = getThen(newValue);
                    if (then === IS_ERROR) {
                        return reject(self, LAST_ERROR);
                    }
                    if (then === self.then && newValue instanceof Promise) {
                        self._state = ADOPTED;
                        self._value = newValue;
                        finale(self);
                        return;
                    } else if (typeof then === 'function') {
                        doResolve(then.bind(newValue), self);
                        return;
                    }
                }
                self._state = FULFILLED;
                self._value = newValue;
                finale(self);
            }
    
            function reject(self, newValue) {
                self._state = REJECTED;
                self._value = newValue;
                if (Promise._onReject) {
                    Promise._onReject(self, newValue);
                }
                finale(self);
            }
    
            function finale(self) {
                if (self._deferredState === FULFILLED) {
                    handle(self, self._deferreds);
                    self._deferreds = null;
                }
                if (self._deferredState === REJECTED) {
                    for (var i = 0; i < self._deferreds.length; i++) {
                        handle(self, self._deferreds[i]);
                    }
                    self._deferreds = null;
                }
            }
    
            function Handler(onFulfilled, onRejected, promise){
                this.onFulfilled = typeof onFulfilled === 'function' ? onFulfilled : null;
                this.onRejected = typeof onRejected === 'function' ? onRejected : null;
                this.promise = promise;
            }
    
            /**
             * Take a potentially misbehaving resolver function and make sure
             * onFulfilled and onRejected are only called once.
             *
             * Makes no guarantees about asynchrony.
             */
            function doResolve(fn, promise) {
                var done = false;
                var res = tryCallTwo(fn, function (value) {
                    if (done) return;
                    done = true;
                    resolve(promise, value);
                }, function (reason) {
                    if (done) return;
                    done = true;
                    reject(promise, reason);
                });
                if (!done && res === IS_ERROR) {
                    done = true;
                    reject(promise, LAST_ERROR);
                }
            }
    
            return Promise
        }) ()
    }

    function isDebug () {
        var debugCheck = document.getElementById('creojsdebug')
        return debugCheck && debugCheck.checked
    }

    function debugPrint (msg) {
        if (isDebug ()) alert (msg)
    }
    
    function getExt (fullName) {
        var found = fullName.match (/\.([^\.\\\/]+)$/);
        if (found) {
            return found [1];
        }
        return "";
    }


    var GUID = GUID || (function() {
        var crypto = window.crypto || window.msCrypto || null; // IE11 fix

        var EMPTY = '00000000-0000-0000-0000-000000000000';

        var _padLeft = function(paddingString, width, replacementChar) {
            return paddingString.length >= width ? paddingString : _padLeft(replacementChar + paddingString, width, replacementChar || ' ');
        };

        var _s4 = function(number) {
            var hexadecimalResult = number.toString(16);
            return _padLeft(hexadecimalResult, 4, '0');
        };

        var _cryptoGuid = function() {
            var buffer = new window.Uint16Array(8);
            crypto.getRandomValues(buffer);
            return [_s4(buffer[0]) + _s4(buffer[1]), _s4(buffer[2]), _s4(buffer[3]), _s4(buffer[4]), _s4(buffer[5]) + _s4(buffer[6]) + _s4(buffer[7])].join('-');
        };

        var _guid = function() {
            var currentDateMilliseconds = new Date().getTime();
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(currentChar) {
                var randomChar = (currentDateMilliseconds + Math.random() * 16) % 16 | 0;
                currentDateMilliseconds = Math.floor(currentDateMilliseconds / 16);
                return (currentChar === 'x' ? randomChar : (randomChar & 0x7 | 0x8)).toString(16);
            });
        };

        var create = function() {
            var hasCrypto = crypto != 'undefined' && crypto !== null,
            hasRandomValues = typeof(crypto.getRandomValues) != 'undefined';
            return (hasCrypto && hasRandomValues) ? _cryptoGuid() : _guid();
        };

        return {
            newGuid: create,
            empty: EMPTY
            };
    })();

    var isLocalPage = window.location.protocol === 'file:';

    var loadTextByURL;

    if (isLocalPage) {
        loadTextByURL = function (url, textHandler, errorHandler) {
            var _loadiframe = document.createElement('iframe');
            _loadiframe.hidden = true;
            document.body.appendChild (_loadiframe);
            _loadiframe.onerror = function () {
                try {
                    if (errorHandler) {
                        errorHandler (url)
                    }
                    else {
                        alert ('Error loading ' + url);
                    }
                    textHandler (null)
                }
                catch (e) {
                    alert (e + ' while loading ' + url);
                }
                finally {
                    document.body.removeChild (_loadiframe);
                }
            }
            
            function showLoadFileFailedMessage (filename) {
                var ext = getExt (filename);
                var ErrMessage = "";
                if (ext) {
                    ErrMessage = "\nPlease check the extension '" + ext + "' of the loaded file.\n" +
                                 "Most likely you have a file-type '." + ext + "' associated with a " + 
                                 "specific program in Windows Explorer. In such case " +
                                 "we suggest removing this association and reload the page.";
                }
                alert ("Failed to load " + filename + ErrMessage);
            }
            _loadiframe.onload = function (){
                try {
                    if (_loadiframe.contentDocument.URL != "about:blank") {
                        textHandler (_loadiframe.contentDocument.body.firstChild.textContent);
                    }
                    else {
                        showLoadFileFailedMessage (_loadiframe.src);
                    }
                }
                catch (e) {
                    alert (e + ' while loading ' + url + "\nPlease check if the file exists.");
                }
                finally {
                    document.body.removeChild (_loadiframe);
                }
            };
            _loadiframe.src = url;
        }
    }
    else {
        function getXMLHttpRequest () {
            try {
                return new XMLHttpRequest();
            }
            catch (e) {
                try {
                    return new ActiveXObject("MSXML2.XMLHTTP.3.0");
                }
                catch (e) {
                    try {
                        return new ActiveXObject("MSXML2.XMLHTTP");
                    }
                    catch (e) {
                        try {
                            return new ActiveXObject("Microsoft.XMLHTTP");
                        }
                        catch(e)    {
                            alert("XMLHTTP Not Supported On Your Browser");
                        }
                    }
                }
            }
        }
        loadTextByURL = function (url, textHandler, errorHandler) {
            var xhttp = getXMLHttpRequest()
            xhttp.onerror = xhttp.onabort = function onError () {
                try {
                    if (errorHandler) {
                        errorHandler (url)
                    }
                    else {
                        alert ('Error loading ' + url);
                    }
                    textHandler (null)
                }
                catch (e) {
                    alert (e + ' while loading ' + url);
                }
            };
            xhttp.onload = function() {
                try {
                    if (this.status == 200) {
                        textHandler (this.responseText);
                    }
                    else {
                        /*
                         * See status values: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status
                         */
                        alert ("Failed to load " + url + "\n" + this.statusText)
                        textHandler (null)
                    }
                }
                catch (e) {
                    alert (e + ' while loading ' + url);
                }
            };
            xhttp.open("GET", url);
            xhttp.setRequestHeader('Cache-Control', 'no-cache')
            xhttp.overrideMimeType("text/raw");
            xhttp.send();
        }
    }
 
    var pageId = GUID.newGuid ();

    var callRegistry = {};
    var callCount = 0;
    
    var IsProxySupported = typeof Proxy !== 'undefined';

    var initializationStartTime = null;
    
    /*
    function buildPayloadMessage (metadata, payload)
    {
        var payloadmsg = "";
        for (var i=0; i<payload.length; i++) {
            if (i % 10 == 0) { payloadmsg += "\n"; }
            payloadmsg += payload.charCodeAt (i) + " ";
        }
        return JSON.stringify (metadata) + '\n| + payloadmsg;
    }
    */
    
    function buildPayloadMessage (payload)
    {
        var payloadmsg = "";
        if (payload) {
            for (var i=0; i<payload.length; i++) {
                if (i % 15 == 0) { payloadmsg += "\n"; }
                payloadmsg += payload.charCodeAt (i) + " ";
            }
        }
        return payloadmsg;
    }
    
    function verifyString (payload) {
        var res = {isOK: true};
        if (payload) {
            try {
                for (var i=0; i<payload.length; i++) {
                    if (payload.charCodeAt (i) == 0xffff) {
                        res.isOK = false;
                        res.position = i+1;
                        res.excerpt = payload.substring (i-45, i) + "<?>";
                        break;
                    }
                }
            }
            catch (err) {}
        }
        return res;
    } 
    
    function getParm (name) {
        var url = window.location.href;
        name = name.replace(/[\[\]]/g, '\\$&');
        var regex = new RegExp('[?&]' + name + '(=([^&#]*)|&|#|$)'),
            results = regex.exec(url);
        if (!results) return undefined;
        if (!results[2]) return '';
        return decodeURIComponent(results[2].replace(/\+/g, ' '));
    }

    var websockAddr = getParm ('ws')
    var socket = null
    
    var socketInitialization = function (initialization) {
        if (initialization) initialization ()
    }

    if (websockAddr) {
        try {
            var wsockUrl = 'ws://' + websockAddr
            socket = new WebSocket (wsockUrl)
            socket.addEventListener('open', function (event) {
                socketInitialization ()
            })
            socket.addEventListener('error', function (event) {
                socket.close ()
                executeDisconnectors ()
            })
            socket.addEventListener('message', function (event) { eval (event.data); })
            socket.addEventListener('close', function (event) {
                executeDisconnectors ()
            })
            var socketInitialized = socketInitialization
            socketInitialization = function (initialization) {
                socketInitialization = initialization || socketInitialized
            }
        }
        catch (ex) {
            alert ("Failed to open websocket on '" + wsockUrl + "': " + String (ex))
        }
    }

    var isCreoAvailable = window.external && window.external.ptc && (typeof window.external.ptc !== 'undefined');
    var checkedAvailability = false

    var resultEval = null
    var frameId= '_top'

    function setIframeServerIfNeeded () {
        var iframeId = getParm ('iframeId')
        var iframeLocator = getParm ('iframeLocator')
        if (iframeLocator || iframeId) {
            setIframeServer ({frameId: iframeId, frameLocator: iframeLocator, origin: getParm ('server')})
        }
    }

    function checkOrigin (event, origin) {
        var eventOrigin = event.origin;
        if (eventOrigin == "file:") {
            /*
             * IE sends "file:" while Chrome send "file://"
             * In location.origin both browosers have "file://"
             */
            eventOrigin += "//";
        }
        return (origin == eventOrigin)
    }

    // options: {frameId: string, frameLocator: string, origin: window.origin}
    function setIframeServer (options) {
        if (options.resultEval) {
            resultEval = options.resultEval
        }
        else {
            var frameLocator = options.frameLocator
            frameId = options.frameId || frameLocator
            if (!frameId) alert ('Either frameId or frameLocator should be passed to CreoJS.setIframeServer')
            frameLocator = frameLocator || 'document.getElementById ("' + frameId + '")'
            resultEval = 'try {var $iframe='+ frameLocator + '; if ($iframe) $iframe.contentWindow.postMessage ({CreoJS: %o},"*")} catch (ex) {}'
        }
        var origin = options.origin || location.origin
        window.addEventListener ('message', function (e) {
            if (checkOrigin (e, origin)) {
                var data = e.data
                if (data && data.CreoJS) {
                    processResponse (data.CreoJS)
                }
            }
        }, false)
    }

    function sendToJSEngine (command, metadata, payload) {
        metadata.client = pageId;
        metadata.command = command;
        if (resultEval) metadata.resultEval = resultEval;
        metadata.frameId = frameId;
        var checkRes = verifyString (payload);
        if (checkRes.isOK) {
            //alert ('StartReplay?' + JSON.stringify (metadata) + '\n|' + buildPayloadMessage (payload))
            //alert ('StartReplay?' + JSON.stringify (metadata, null, 2))
            var message = JSON.stringify (metadata) + '\n|\n' + (payload ? payload : '')
            if (socket) {
                socket.send (message)
            }
            else {            
                if (!checkedAvailability) {
                    checkedAvailability = true
                    if (!isCreoAvailable) {
                        alert ('The page attempts to access Creo environment which is not supported by your browser. Some functionalty may not be available')
                    }
                }
                if (isCreoAvailable) {
                    window.external.ptc ('ToolkitJSBridge=v8?' + message);
               }
            }
        }
        else {
            alert ("Failed to send " + metadata.resource + ": symbol at position " + checkRes.position + "\n" + 
                checkRes.excerpt + "\n" +"Please verify this file is UTF encoded");
        }
    }

    var initialized = false
    var CREO_JS_ON_TERMINATE_SCRIPT ="if ((typeof CreoJS !== 'undefined') && CreoJS.terminate) try {CreoJS.terminate (); CreoJS = undefined;} catch (ex) {}"

    function getAbsoluteHref (url) {
        var link = document.createElement('a');
        link.href = url
        // alert ('url: ' + url + ', link: ' + link.href)
        return '' + link.href
    }

    function getJSName (type, id) {
        return type ? ('$' + type + (id ? ('_' + id) : '') + '.js') : id
    }

    function getLocalHref (id, type, hidden) {
        if (type) id = getJSName (type, id)
        if (hidden) id = '$hidden/' + id
        return location.origin + location.pathname + '/' + id // + location.search
    }    

    function initialize (initScript) {
        if (window !== window.top) {
            if (!resultEval) {
                var initSendToCreoJS = '(' + function (checkOrigin) {
                    window.sendToCreoJS = function (msg) {
                        try {
                            var path = msg.path
                            if (path.length) {
                                var $iframe = window.document.getElementById (path.shift ())
                                if ($iframe) {
                                    $iframe.contentWindow.postMessage (msg, "*")
                                }
                            }
                            else {
                                alert ('wrong turn')
                            }
                        }
                        catch (ex) {} // ignore
                    }
                    window.addEventListener ('message', function (e) {
                        if (checkOrigin (e, location.origin)) {
                            var data = e.data
                            if (data && data.CreoJS) {
                                window.sendToCreoJS (data)
                            }
                        }
                    }, false)
                } + ') (' + checkOrigin + ')'
                function findParentIframe (window) {
					var parentIFrames = window.parent.document.getElementsByTagName ('iframe')
					for (var idx = 0; idx < parentIFrames.length; idx++) {
						var frame = parentIFrames [idx]
						var frameDoc = frame.contentWindow.document
						var frameId = frame.id
						if (frameDoc === window.document) {
							if (!frameId) {
								frameId = frame.id = 'creojs-' + pageId
							}
							return frame
						}
					}
                    return null
                }
                // Attempt to autodetect iframe server parameters if the parent window is from the same server
                try {
                    var path = []
                    var curWindow = window
                    do {
                        var iframe = findParentIframe (curWindow)
                        path.unshift (iframe.id)
                        curWindow = curWindow.parent
                        if (!curWindow.sendToCreoJS) {
                            curWindow.eval (initSendToCreoJS)
                        }
                    } while (curWindow !== window.top)
                    if (path.length) {
                        setIframeServer ({resultEval: 'try {window.sendToCreoJS ({path: ' + JSON.stringify (path) + ', CreoJS: %o},"*")} catch (ex) {}'})
                    }
                }
                catch (ex) {
                    // Something went wrong - ignore and show general error
                }
            }
            if (!resultEval) {
                alert ("ERROR: Initializing Creo.JS in non-top frame without defining frame resolver")
            }
        }
        if (resultEval) {
            initScript += '\nCreoJS.resultEval = "' + resultEval.replace (/\"/g, "\\\"") + '"'
        }
        initializationStartTime = new Date ()
        var pageUrl = String (window.location)
        sendToJSEngine ('init', {title: document.title || pageUrl, location: pageUrl, href: getLocalHref (null, 'start_init', true), hidden: true}, initScript)
        sendToJSEngine ('onterm', {}, CREO_JS_ON_TERMINATE_SCRIPT)
        var jsscripts = []
        var scripts = document.scripts
        for (var idx=0; idx < scripts.length; idx++) {
            var scriptElement = scripts [idx]
            if (scriptElement.type === 'text/creojs') {
                jsscripts.push (scriptElement)
            }
        }
        scripts = document.getElementsByTagName("creojs")
        for (var idx=0; idx < scripts.length; idx++) {
            var scriptElement = scripts [idx]
            scriptElement.style.display = 'none'
            jsscripts.push (scriptElement)
        }
        var inlineId = 0
        function completeInitialization () {
            if (jsscripts.length === 0) {
                sendToJSEngine ('run', {href: getLocalHref (null, 'complete_init', true), hidden: true}, 'CreoJS.initialize ()')
                initialized = true
                initializers.forEach (function (initializer) {initializer ()})
            }
            else {
                var scriptElement = jsscripts.shift ()
                var src = scriptElement.getAttribute ('src')
                var id = scriptElement.id
                var isEmptyId = !id || id.length == 0
                if (src && src.length > 0) {
                    if (isEmptyId) id = src
                    loadScriptByUrl (src, id, getAbsoluteHref (id))
                }
                else {
                    if (isEmptyId) id = getJSName ('inline', ++inlineId)
                    loadScript (scriptElement.textContent, id, getLocalHref (id))
                    completeInitialization ()
                }
            }
        }
        function loadScriptByUrl (src, id, href) {
            if (src.match (/^https?:/)) {
                CreoJS.$ ('downloadString', true) (src).then (function (script) {
                    if (script) loadScript (script, id, href)
                    completeInitialization ()
                }).catch (function (ex) {
                    alert ('Failed to load ' + src)
                })
            }
            else {
                loadTextByURL (src, function (script) {
                    if (script) loadScript (script, id, href)
                    completeInitialization ()
                })
            }
        }
        completeInitialization ()
    }

    var fileConsumer = null;

    function readFile (filename, consumer) {
        fileConsumer = consumer;
        if (consumer) {
            sendToJSEngine ('load', {file: filename})
        }
    }

    function writeFile (filename, content) {
        sendToJSEngine ('save', {file: filename}, content)
    }

    function loadScript (script, sourceOrigin, href, hidden) {
        if (!IsProxySupported) {
            //alert ("Loaded script: sourceOrigin: " + sourceOrigin)
            var functionFinder = /function[\s]+([A-Za-z_]\w+)/g
            var functionData;
            try {
                while ((functionData = functionFinder.exec(script)) !== null) {
                    var funcName = functionData [1]
                    // alert ('loading function ' + funcName)
                    connector.$ (funcName)
                    debugPrint(funcName);
                }
            }
            catch (ex) {
                alert ("exception: " + ex)
            }
        }
        sendToJSEngine ('exec', {resource: sourceOrigin, hidden: Boolean (hidden), href: href}, script)
    }

    function runScript (id, script, hidden) {
        sendToJSEngine ('run', {resource: 'call.' + id, id: '' + id, hidden: Boolean (hidden), href: getLocalHref (id, 'call', hidden)}, script)
    }

    function executeScript (id, script, url, hidden) {
        id = String (id)
        sendToJSEngine ('exec', {resource: id, id: id, hidden: Boolean (hidden), href: url || getLocalHref (id, null, hidden)}, script)
    }

    function callScript (script) {
        var id = '$' + callCount++
        var startTime = new Date ()
        // script = "try {JSON.stringify ({type: 'return', obj:" + ' (function() {' + script +
        //     "})()})} catch (ex) {if (ex instanceof Error) throw ex; JSON.stringify ({type: 'exception', obj:ex})}"
        runScript (id, script, true)
        return new CallPromise (id, startTime)
    }

    function processResponse (msg) {
        setTimeout (function () {
            if (msg) {
                debugPrint (JSON.stringify (msg))
                if (msg.line) {
                  if (connector.$ONPRINT) {
                    connector.$ONPRINT (msg.line)
                  }
                }
                if (msg.script) {
                    if (fileConsumer) {
                        fileConsumer (msg.script)
                    }
                }
                if (msg.exception) {
                    if (msg.exception.client === pageId)
                    {
                        var listener = callRegistry [msg.exception.id]
                        if (listener) {
                            if (listener.onError) {
                              listener.onError (msg.exception, listener.callTime)
                            }
                            else {
                              connector.$ONERROR (msg.exception, listener.callTime)
                            }
                            listener.onFinally (listener.callTime)
                            delete callRegistry [msg.exception.id]
                        }
                        else {
                            connector.$ONERROR (msg.exception)
                        }
                    }
                    else {
                        connector.$ONERROR (msg.exception)
                    }
                }
                if (msg.result) {
                    if (msg.result.client === pageId)
                    {
                        var id = msg.result.id
                        var listener = callRegistry [id]
                        if (listener) {
                            var value = msg.result.value
                            if (value && (value.type == 'exception')) {
                                if (listener.onException) {
                                    listener.onException (msg.result.value.obj, listener.callTime)
                                }
                                else if (connector.$ONEXCEPTION) {
                                    connector.$ONEXCEPTION (msg.result.value.obj, listener.callTime)
                                }
                            }
                            else if (listener.listener) {
                                if (id.indexOf ('$') !== 0) value = value.obj
                                listener.listener (value, listener.callTime)
                            }
                            listener.onFinally (listener.callTime)
                            delete callRegistry [msg.result.id]
                        }
                    }                             
                }
                if (msg.refresh) {
                    if (connector.$ONREFRESH) {
                        connector.$ONREFRESH (msg.refresh)
                    }
                }
                if (msg.browser) {
                    if (connector.$CALLBROWSER) {
                        connector.$CALLBROWSER (msg.browser.id, function () {
                            var obj = eval (msg.browser.name)
                            var args = msg.browser.args
                            if (typeof args === 'string') args = JSON.parse (args, connector.$CALLFUNC)
                            return (typeof obj === 'function') ? obj.apply (null, args) : obj
                        })
                    }
                }
                if (msg.alert) {
                    alert (msg.alert);
                }
                if ("help_request" in msg) {
                    if (connector.$ONHELP) {
                        connector.$ONHELP (msg);
                    }
                }
            }
        })
    }

    var CallPromise = function (callId, startTime) {
        var subscribed = false
        var exceptionHandlers = []
        var errorHandlers = []
        var finallyHandlers = []
        var subscribers = []
        function handleException (exc, startTime) {
            if (exceptionHandlers) {
                if (exceptionHandlers.length > 0) {
                    exceptionHandlers.forEach (function (handler) {handler (exc, startTime)})
                }
                else if (connector.$ONEXCEPTION) {
                    connector.$ONEXCEPTION (exc, startTime)
                }
            }
        }
        function handleError (err, startTime) {
            if (errorHandlers) {
                if (errorHandlers.length > 0) {
                    errorHandlers.forEach (function (handler) {handler (err, startTime)})
                }
                else if (connector.$ONERROR) {
                    connector.$ONERROR (err, startTime)
                }
            }
        }
        function handleFinally (startTime) {
            if (finallyHandlers && (finallyHandlers.length > 0)) {
                finallyHandlers.forEach (function (handler) {handler (startTime)})
            }
        }
        function NOOP (v) {return v;}
        function chainSubscriber (subscriber) {
            return function (value, startTime) {
                var startNextTime = new Date ()
                try {
                    var next = undefined
                    if (subscriber) {
                        next = subscriber (value, startTime)
                    }
                    if (!subscriber || (subscriber === NOOP)) {
                        startNextTime = startTime
                    }
                    if (subscribers.length > 0) {
                        var nextSubscriber = chainSubscriber (subscribers.shift ())
                        if (next instanceof CallPromise) {
                            next.subscribe (nextSubscriber)
                            if (exceptionHandlers) exceptionHandlers.forEach (function (handler) {next.onException (handler)})
                            if (errorHandlers) errorHandlers.forEach (function (handler) {next.onError (handler)})
                            if (finallyHandlers) finallyHandlers.forEach (function (handler) {next.finally (handler)})
                        }
                        else {
                            nextSubscriber (next, startNextTime)
                        }
                    }
                }
                catch (ex) {
                    if (ex instanceof Error) {
                        handleError (ex, startNextTime)
                    }
                    else {
                        handleException (ex, startNextTime)
                    }
                }
            }
        }
        callRegistry [callId] = {listener: chainSubscriber (NOOP), onException: handleException, onError: handleError, onFinally: handleFinally, callTime: startTime}
        this.subscribe = function (subscriber) {
            subscribers.push (subscriber)
            return this
        }
        this.then = this.subscribe
        this.onError = function (handler) {
            if (handler) {
                if (errorHandlers) errorHandlers.push (handler)
            }
            else {
                errorHandlers = null
            }
            return this
        }
        this.onException = function (handler) {
            if (handler) {
                if (exceptionHandlers) exceptionHandlers.push (handler)
            }
            else {
                exceptionHandlers = null
            }
            return this
        }
        this.finally = function (handler) {
            if (handler) {
                if (finallyHandlers) finallyHandlers.push (handler)
            }
            else {
                finallyHandlers = null
            }
            return this
        }
        this.catch = function (handler) {this.onError (handler); return this.onException (handler)}
    }

    function scriptCaller (target, name, beforeInit) {
        if (! (name in target)) {
            target [name] = function () {
                if (!beforeInit && !initialized) throw new Error ('Calling CreoJS.' + name + '() before page initialization completed')
                script = "CreoJS.execute (function () { return " + name + "(";
                var sep = ''
                for (var i=0; i < arguments.length; i++) {
                    script += sep + JSON.stringify (arguments [i])
                    sep = ','
                }
                script += "); });"
                var id = '' + callCount++
                var startTime = new Date ()
                runScript (id, script, true)
                return new CallPromise (id, startTime)
            }
        }
        return target [name]
    }

    function onPrint (line) {
        alert (line)
    }

    function onException (exc, startTime) {
        alert (JSON.stringify (exc))
    }

    function onHelp (url) {
        alert (JSON.stringify (msg));
    }

    function onError (exc, startTime) {
        var message = exc.message
        if (!message || (message.search ('Error:') < 0)) message = 'Error: ' + message
        if (exc.resource) {
            message += "\nin " + exc.resource;
            if (exc.line) {
                message += ":" + exc.line;
                if (typeof (exc.source_line_start) === "number") {
                    message += ":" + exc.source_line_start;
                }
            }
            if (exc.source_line) {
                message += "\n---------\n " + (exc.line ? exc.line+": " : "") + exc.source_line + "\n---------";
            }
        }
        var count = 1
        var traceback = exc.traceback
        if (traceback && traceback.length > 0) {
            exc.traceback.forEach (function (frame) {
                var funcname = frame.funcname
                if (funcname === '')
                    funcname = 'SCRIPT'
                else
                    funcname += ' ()'
                message += '\n' + count++ + ') ' + funcname + ' [' + frame.resource + ':' + frame.line + ':' + frame.column + ']'
            })
        }
        else {
            message = 'Error [' + exc.id + ':' + exc.line + ']: ' + exc.message
        }
        alert (message, "Application Error")
    }

    var autoinitialization = true

    function onLoadInitialization () {
        if (autoinitialization) {
            socketInitialization (function () {
                initialize ("let CreoJS = (function () {const unloadListeners = []; const loadListeners = []; const actionListeners = []; \
                    return {set onunload (value) {unloadListeners.push (value)}, \
                            set onload (value) {loadListeners.push (value)}, \
                            execute (func) { try { \
                                const retVal = func ();\
                                if (retVal instanceof Promise) { return retVal; } \
                                return JSON.stringify ({type: 'return', obj: retVal })\
                              } \
                              catch (ex) { if (ex instanceof Error) throw ex; return JSON.stringify ({type: 'exception', obj:ex}); }}, \
                            addListener (owner, listener) {actionListeners.push ({owner, listener}); owner.AddActionListener (listener)}, \
                            removeListener (owner, listener) {let idx = actionListeners.findIndex (e=>e.owner===owner && e.listener===listener); if (idx > -1) { \
                                owner.RemoveActionListener (listener);  actionListeners.splice (idx, 1)}}, \
                            clearListeners (owner) {let idx; while ((idx=actionListeners.findIndex (e=>!owner||e.owner===owner))>-1) { \
                                const e=actionListeners[idx]; e.owner.RemoveActionListener (e.listener);  actionListeners.splice (idx, 1)}}, \
                            initialize () {loadListeners.forEach (h => h ()); loadListeners.splice (0)}, \
                            terminate () {unloadListeners.forEach (h => h ()); unloadListeners.splice (0)}}}) ()")
                /****************************************************************************************************************************** 
                 * DD: 'unload' event does not always work as intended. Quoting Omer Balash message:
                 * I am looking at the behavior of CEF and indeed onunload is called after navigation is already in progress to the new page and 
                 * cannot reliably used for your purpose. but it looks llike onbeforeunload is called in the opportune time for you and should 
                 * allow this JSCB to work as you expect (assuming you register it as sync)
                 ******************************************************************************************************************************/
                //window.addEventListener ('unload', onUnloadTermination)
                window.addEventListener ('beforeunload', onUnloadTermination)
            })
        }
    }
    
    window.addEventListener ('load', onLoadInitialization)

    function onUnloadTermination () {
        if (initialized) {
            terminators.forEach (function (terminator) {terminator ()})
            sendToJSEngine ('term', {}, CREO_JS_ON_TERMINATE_SCRIPT)
            initialized = false
        }
    }

    var initializers = []

    function addInitializer (initializer) {
        if (typeof initializer === 'function') {
            if (initialized) {
                initializer ()
            }
            else {
                initializers.push (initializer)
            }
        }
        else {
            throw new Error ('Initializer is not a function')
        }
    }

    var terminators = []

    function addTerminator (terminator) {
        if (typeof terminator === 'function') {
            terminators.push (terminator)
        }
        else {
            throw new Error ('Terminator is not a function')
        }
    }

    var disconnectors = []

    function addDisconnector (disconnector) {
        if (typeof disconnector === 'function') {
            disconnectors.push (disconnector)
        }
        else {
            throw new Error ('Disconnector is not a function')
        }
    }

    function executeDisconnectors () {
        if (socket) {
            if (disconnectors.length) {
                disconnectors.forEach (function (disconnector) {disconnector ()})
            }
            else {
                alert ('Connection to Creo session lost')
            }
            socket = null
        }
    }

    function resetContext () {
        onUnloadTermination ()
        pageId = GUID.newGuid ()
        onLoadInitialization ()
    }

    function callBrowser (id, cb) {
        function reply (obj) {
            obj.id = id
            executeScript ('$return_' + id, 'Browser.$ONRETURN (' + JSON.stringify (obj) + ')', null, true)
        }
        try {
            reply ({value: cb ()})
        }
        catch (ex) {
            reply (ex instanceof Error ? {error: ex.message} : {exception: ex})
        }
    }

    var connector = {
        isAvailable: function () {return isCreoAvailable},
        $: function (name, beforeInit) {return scriptCaller (this, name, beforeInit);},
        $SET_IFRAME_SERVER: setIframeServer,
        $INIT_IFRAME_SERVER: setIframeServerIfNeeded,
        $ADD_ON_LOAD: addInitializer,
        $ADD_ON_UNLOAD: addTerminator,
        $ADD_ON_DISCONNECT: addDisconnector,
        $CALLBROWSER: callBrowser,
        $EXEC: executeScript,
        $CALL: callScript,
        $LOAD: readFile,
        $SAVE: writeFile,
        $ONPRINT: onPrint,
        $ONREFRESH: null,
        $ONEXCEPTION: onException,
        $ONERROR: onError,
        $ONHELP: onHelp,
        $ONRESPONSE: processResponse,
        $CALLFUNC: null,
        $GUID: pageId,
        $RESET: resetContext,
        $AUTOINITIALIZATION: function (on) { autoinitialization = on; },
        $INITIALIZE: function () {if (!initialized) { autoinitialization = true; onLoadInitialization () }},
        $GET_LOCAL_HREF: function (path) {return getLocalHref (path);},
        $GET_ABSOLUTE_HREF: function (path) {return getAbsoluteHref (path);},
        $LOAD_SCRIPT: function (script, origin, hidden) {loadScript (script, origin || 'dynamic', hidden);},
        $LOAD_TEXT_BY_URL: loadTextByURL,
        $LOAD_SCRIPT_BY_URL: function (url, hidden) {loadTextByURL (url, function (script) {if (script) loadScript (script, url, hidden);})},
        $PARM: getParm
    }
    return IsProxySupported ? new Proxy (connector, {get: scriptCaller}) : connector;
}) ();
