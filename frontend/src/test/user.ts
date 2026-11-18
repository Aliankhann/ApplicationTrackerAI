import { fireEvent } from '@testing-library/react'

// Minimal stand-in for user-event (not a dependency): fireEvent already wraps updates in act().
type Field = HTMLInputElement | HTMLSelectElement

const userEvent = {
  setup: () => ({
    click: async (el: Element) => void fireEvent.click(el),
    selectOptions: async (el: HTMLElement, value: string) =>
      void fireEvent.change(el, { target: { value } }),
    clear: async (el: HTMLElement) => void fireEvent.change(el, { target: { value: '' } }),
    type: async (el: HTMLElement, text: string) =>
      void fireEvent.change(el, {
        target: { value: (el as Field).value + text },
      }),
  }),
}
export default userEvent
