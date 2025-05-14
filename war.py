"""
war card game client and server
"""
import asyncio
from collections import namedtuple
from csv import reader
from enum import Enum
import logging
import random
import socket
import socketserver
import threading
import sys


"""
Namedtuples work like classes, but are much more lightweight so they end
up being faster. It would be a good idea to keep objects in each of these
for each game which contain the game's state, for instance things like the
socket, the cards given, the cards still available, etc.
"""
Game = namedtuple("Game", ["p1", "p2"])

# Stores the clients waiting to get connected to other clients
waiting_clients = []


class Command(Enum):
    """
    The byte values sent as the first byte of any message in the war protocol.
    """
    WANTGAME = 0
    GAMESTART = 1
    PLAYCARD = 2
    PLAYRESULT = 3


class Result(Enum):
    """
    The byte values sent as the payload byte of a PLAYRESULT message.
    """
    WIN = 0
    DRAW = 1
    LOSE = 2

async def readexactly(sock, numbytes):
    """
    Accumulate exactly `numbytes` from `sock` and return those. If EOF is found
    before numbytes have been received, be sure to account for that here or in
    the caller.
    """
    data = b''
    while len(data) < numbytes:
        chunk = await reader.read(numbytes - len(data))
        if not chunk:
            raise ConnectionError("Incomplete data received.")
        data += chunk
    return data


async def kill_game(game):
    """
    TODO: If either client sends a bad message, immediately nuke the game.
    """
    logging.error("Killing game due to bad message.")
    game.p1.close()
    game.p2.close()
    await game.p1.wait_closed()
    await game.p2.wait_closed()


def compare_cards(card1, card2):
    """
    TODO: Given an integer card representation, return -1 for card1 < card2,
    0 for card1 = card2, and 1 for card1 > card2
    """
    value1 = card1 % 13
    value2 = card2 % 13
    if value1 > value2:
        return 1
    elif value1 < value2:
        return -1
    return 0
    

def deal_cards():
    """
    TODO: Randomize a deck of cards (list of ints 0..51), and return two
    26 card "hands."
    """
    deck = list(range(52))
    random.shuffle(deck)
    return deck[:26], deck[26:]
    

def serve_game(host, port):
    """
    TODO: Open a socket for listening for new connections on host:port, and
    perform the war protocol to serve a game of war between each client.
    This function should run forever, continually serving clients.
    """
    async def handle_game(reader1, writer1, reader2, writer2):
        game = Game(writer1, writer2)
        try:
            msg1 = await readexactly(reader1, 2)
            msg2 = await readexactly(reader2, 2)
            if msg1[0] != Command.WANTGAME.value or msg1[1] != 0:
                await kill_game(game)
                return
            if msg2[0] != Command.WANTGAME.value or msg2[1] != 0:
                await kill_game(game)
                return

            hand1, hand2 = deal_cards()
            writer1.write(bytes([Command.GAMESTART.value]) + bytes(hand1))
            writer2.write(bytes([Command.GAMESTART.value]) + bytes(hand2))
            await writer1.drain()
            await writer2.drain()

            used1 = set()
            used2 = set()

            for _ in range(26):
                play1 = await readexactly(reader1, 2)
                play2 = await readexactly(reader2, 2)

                if play1[0] != Command.PLAYCARD.value or play2[0] != Command.PLAYCARD.value:
                    await kill_game(game)
                    return

                card1 = play1[1]
                card2 = play2[1]

                if card1 in used1 or card2 in used2:
                    await kill_game(game)
                    return

                used1.add(card1)
                used2.add(card2)

                result = compare_cards(card1, card2)
                if result == 1:
                    writer1.write(bytes([Command.PLAYRESULT.value, Result.WIN.value]))
                    writer2.write(bytes([Command.PLAYRESULT.value, Result.LOSE.value]))
                elif result == -1:
                    writer1.write(bytes([Command.PLAYRESULT.value, Result.LOSE.value]))
                    writer2.write(bytes([Command.PLAYRESULT.value, Result.WIN.value]))
                else:
                    writer1.write(bytes([Command.PLAYRESULT.value, Result.DRAW.value]))
                    writer2.write(bytes([Command.PLAYRESULT.value, Result.DRAW.value]))

                await writer1.drain()
                await writer2.drain()

            writer1.close()
            writer2.close()
            await writer1.wait_closed()
            await writer2.wait_closed()

        except Exception as e:
            logging.error(f"Error during game: {e}")
            await kill_game(game)
    

async def limit_client(host, port, loop, sem):
    """
    Limit the number of clients currently executing.
    You do not need to change this function.
    """
    async with sem:
        return await client(host, port, loop)

async def client(host, port, loop):
    """
    Run an individual client on a given event loop.
    You do not need to change this function.
    """
    try:
        reader, writer = await asyncio.open_connection(host, port)
        # send want game
        writer.write(b"\0\0")
        card_msg = await reader.readexactly(27)
        myscore = 0
        for card in card_msg[1:]:
            writer.write(bytes([Command.PLAYCARD.value, card]))
            result = await reader.readexactly(2)
            if result[1] == Result.WIN.value:
                myscore += 1
            elif result[1] == Result.LOSE.value:
                myscore -= 1
        if myscore > 0:
            result = "won"
        elif myscore < 0:
            result = "lost"
        else:
            result = "drew"
        logging.debug("Game complete, I %s", result)
        writer.close()
        return 1
    except ConnectionResetError:
        logging.error("ConnectionResetError")
        return 0
    except asyncio.streams.IncompleteReadError:
        logging.error("asyncio.streams.IncompleteReadError")
        return 0
    except OSError:
        logging.error("OSError")
        return 0

def main(args):
    """
    launch a client/server
    """
    host = args[1]
    port = int(args[2])
    if args[0] == "server":
        try:
            # your server should serve clients until the user presses ctrl+c
            serve_game(host, port)
        except KeyboardInterrupt:
            pass
        return
    else:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        
        asyncio.set_event_loop(loop)
        
    if args[0] == "client":
        loop.run_until_complete(client(host, port, loop))
    elif args[0] == "clients":
        sem = asyncio.Semaphore(1000)
        num_clients = int(args[3])
        clients = [limit_client(host, port, loop, sem)
                   for x in range(num_clients)]
        async def run_all_clients():
            """
            use `as_completed` to spawn all clients simultaneously
            and collect their results in arbitrary order.
            """
            completed_clients = 0
            for client_result in asyncio.as_completed(clients):
                completed_clients += await client_result
            return completed_clients
        res = loop.run_until_complete(
            asyncio.Task(run_all_clients(), loop=loop))
        logging.info("%d completed clients", res)

    loop.close()

if __name__ == "__main__":
    # Changing logging to DEBUG
    logging.basicConfig(level=logging.DEBUG)
    main(sys.argv[1:])
