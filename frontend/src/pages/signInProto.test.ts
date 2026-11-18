import { describe, expect, it } from 'vitest'
import { messageForError } from './signIn'

describe('messageForError prototype keys', () => {
  it.fails.each(['__proto__', 'constructor', 'toString', 'hasOwnProperty'])('%s yields a string', (k) => {
    expect(typeof messageForError(k)).toBe('string')
  })
})
