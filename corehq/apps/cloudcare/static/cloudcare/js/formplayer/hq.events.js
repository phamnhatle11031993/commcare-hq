/*global FormplayerFrontend */

/**
 * hq.events.js
 *
 * This is framework for allowing messages from HQ
 */
FormplayerFrontend.module("HQ.Events", function(Events, FormplayerFrontend) {

    Events.Receiver = function(allowedHost) {
        this.allowedHost = allowedHost;
        return receiver.bind(this);
    };

    var receiver = function(event) {
        // For Chrome, the origin property is in the event.originalEvent object
        var origin = event.origin || event.originalEvent.origin,
            data = event.data,
            returnValue = null,
            success = true;

        _.defaults(data, {
            success: function() {},
            error: function() {},
            complete: function() {},
        });
        if (!origin.endsWith(this.allowedHost)) {
            throw new Error('Disallowed origin ' + origin);
        }

        if (!data.hasOwnProperty('action')) {
            throw new Error('Message must have action property');
        }
        if (!_.contains(_.values(Events.Actions), data.action)) {
            throw new Error('Invalid action ' + data.action);
        }

        try {
            switch (data.action) {
            case Events.Actions.BACK:
                FormplayerFrontend.trigger('navigation:back');
                break;
            }
        } catch (e) {
            success = false;
            data.error(event, data, returnValue);
        } finally {
            data.complete(event, data, returnValue);
        }
        if (success) {
            data.success(event, data, returnValue);
        }
    };

    Events.Actions = {
        BACK: 'back',
    };
});
