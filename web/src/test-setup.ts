import "@testing-library/jest-dom/vitest";

// jsdom lacks these; Radix (dropdowns, dialogs) calls them.
Element.prototype.hasPointerCapture = () => false;
Element.prototype.setPointerCapture = () => {};
Element.prototype.releasePointerCapture = () => {};
Element.prototype.scrollIntoView = () => {};
