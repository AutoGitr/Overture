import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import ColorInput from "../../../lib/components/ColorInput.svelte";

describe("ColorInput", () => {
  it("renders with initial hex value in both text input and color swatch", () => {
    render(ColorInput, {
      value: "#6366f1",
      id: "accent-color",
      label: "Accent Color",
    });

    const textInput = screen.getByLabelText("Accent Color hex value");
    const swatchInput = screen.getByLabelText("Accent Color picker");

    expect(textInput).toHaveValue("#6366f1");
    expect(swatchInput).toHaveValue("#6366f1");
  });

  it("updates value and hex text when native color swatch fires input event", async () => {
    render(ColorInput, {
      value: "#6366f1",
      label: "Accent Color",
    });

    const swatchInput = screen.getByLabelText("Accent Color picker");
    const textInput = screen.getByLabelText("Accent Color hex value");

    await fireEvent.input(swatchInput, { target: { value: "#10b981" } });

    expect(textInput).toHaveValue("#10b981");
    expect(swatchInput).toHaveValue("#10b981");
  });

  it("updates bound value and swatch in real time when valid hex is typed", async () => {
    render(ColorInput, {
      value: "#6366f1",
      label: "Accent Color",
    });

    const textInput = screen.getByLabelText("Accent Color hex value");
    const swatchInput = screen.getByLabelText("Accent Color picker");

    await fireEvent.focus(textInput);
    await fireEvent.input(textInput, { target: { value: "ff0055" } });

    expect(textInput).toHaveValue("ff0055");
    expect(swatchInput).toHaveValue("#ff0055");

    await fireEvent.blur(textInput);
    expect(textInput).toHaveValue("#ff0055");
  });

  it("expands 3-digit shorthand to 6 digits on blur", async () => {
    render(ColorInput, {
      value: "#6366f1",
      label: "Accent Color",
    });

    const textInput = screen.getByLabelText("Accent Color hex value");
    const swatchInput = screen.getByLabelText("Accent Color picker");

    await fireEvent.focus(textInput);
    await fireEvent.input(textInput, { target: { value: "#f05" } });

    expect(swatchInput).toHaveValue("#ff0055");

    await fireEvent.blur(textInput);
    expect(textInput).toHaveValue("#ff0055");
  });

  it("reverts invalid hex text on blur to the last valid color", async () => {
    render(ColorInput, {
      value: "#6366f1",
      label: "Accent Color",
    });

    const textInput = screen.getByLabelText("Accent Color hex value");
    const swatchInput = screen.getByLabelText("Accent Color picker");

    await fireEvent.focus(textInput);
    await fireEvent.input(textInput, { target: { value: "not-a-color" } });

    expect(swatchInput).toHaveValue("#6366f1");

    await fireEvent.blur(textInput);
    expect(textInput).toHaveValue("#6366f1");
  });

  it("blurs and normalizes when Enter is pressed", async () => {
    render(ColorInput, {
      value: "#6366f1",
      label: "Accent Color",
    });

    const textInput = screen.getByLabelText("Accent Color hex value");
    await fireEvent.focus(textInput);
    await fireEvent.input(textInput, { target: { value: "123456" } });

    await fireEvent.keyDown(textInput, { key: "Enter" });
    expect(textInput).toHaveValue("#123456");
  });

  it("reverts to pre-focus value when Escape is pressed", async () => {
    render(ColorInput, {
      value: "#6366f1",
      label: "Accent Color",
    });

    const textInput = screen.getByLabelText("Accent Color hex value");
    const swatchInput = screen.getByLabelText("Accent Color picker");

    await fireEvent.focus(textInput);
    await fireEvent.input(textInput, { target: { value: "#ff0000" } });
    expect(swatchInput).toHaveValue("#ff0000");

    await fireEvent.keyDown(textInput, { key: "Escape" });
    expect(textInput).toHaveValue("#6366f1");
    expect(swatchInput).toHaveValue("#6366f1");
  });

  it("respects disabled prop on both swatch and text inputs", () => {
    render(ColorInput, {
      value: "#6366f1",
      label: "Accent Color",
      disabled: true,
    });

    expect(screen.getByLabelText("Accent Color hex value")).toBeDisabled();
    expect(screen.getByLabelText("Accent Color picker")).toBeDisabled();
  });
});
