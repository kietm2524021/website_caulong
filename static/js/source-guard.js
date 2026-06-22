(function () {
    "use strict";

    function blockShortcut(event) {
        var key = String(event.key || "").toLowerCase();
        var blocked = event.key === "F12"
            || (event.ctrlKey && key === "u")
            || (event.ctrlKey && event.shiftKey && ["i", "j", "c"].includes(key));

        if (blocked) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }

    document.addEventListener("keydown", blockShortcut, true);
    document.addEventListener("contextmenu", function (event) {
        event.preventDefault();
    }, true);
}());
