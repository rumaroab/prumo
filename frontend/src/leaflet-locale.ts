import { Control, Map } from "leaflet";

Control.Zoom.mergeOptions({
  zoomInTitle: "Aproximar mapa",
  zoomOutTitle: "Afastar mapa",
});

Map.addInitHook(function (this: Map) {
  this.on("popupopen", ({ popup }) => {
    const close = popup.getElement()?.querySelector<HTMLElement>(".leaflet-popup-close-button");
    if (close) {
      close.title = "Fechar janela";
      close.setAttribute("aria-label", "Fechar janela");
    }
  });
});
