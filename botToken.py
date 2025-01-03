import os
import logging

def get_token(file_name: str) -> str:
    token_path = os.path.join(os.path.dirname(__file__), file_name)

    try:
        with open(token_path, "r") as file:
            token = file.readlines()

            if len(token) > 0:
                token = token[0]
            else:
                print(f"No token found in file \"{os.path.basename(token_path)}\".")
                exit(1)
    except FileNotFoundError:
        print(f"No {os.path.basename(token_path)} file found.")
        usr_token_string = input("Enter bot token: ")

        if len(usr_token_string) > 0:

            with open(token_path, "w") as file:
                file.write(usr_token_string)
        else:
            print("No token has been passed. Program will fail to connect to Discord.")

        return usr_token_string
    except OSError as e:
        print(f"Error while accessing file \"{os.path.basename(token_path)}\"\n{e}")
        logging.error(f"An error occured while accessing bot token file; {e}")
        exit(1)

    return token
